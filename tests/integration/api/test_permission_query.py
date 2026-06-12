from __future__ import annotations

from datetime import datetime, timedelta
from http import HTTPStatus
from re import escape, findall, search
from typing import TYPE_CHECKING, Final, Protocol

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode
from easyauth.applications.models import (
    App,
    AppStaticToken,
    Permission,
    Role,
    RolePermission,
)
from easyauth.applications.services import StaticTokenService
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    GRANT_STATUS_EXPIRED,
    GRANT_STATUS_REVOKED,
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    AccessGrant,
    AccessGrantPermission,
    AccessGrantRole,
)

if TYPE_CHECKING:
    from easyauth.api.serializers import PermissionQueryResponsePayload

pytestmark = pytest.mark.django_db

PERMISSION_QUERY_TTL_SECONDS: Final = 120


class HttpResponseLike(Protocol):
    status_code: int
    content: bytes


@override_settings(EASYAUTH_PERMISSION_QUERY_CACHE_TTL_SECONDS=PERMISSION_QUERY_TTL_SECONDS)
def test_permission_query_returns_active_roles_permissions_version_expiration_and_audit() -> None:
    # Given: 应用静态 token 绑定了当前应用, 用户有当前有效授权。
    user = UserMirror.objects.create(authentik_user_id="user-api-active")
    app = App.objects.create(app_key="crm-api-active", name="CRM API Active")
    issue = StaticTokenService.create_token(app=app, name="CRM integration")
    admin = Role.objects.create(app=app, key="admin", name="Admin")
    auditor = Role.objects.create(app=app, key="auditor", name="Auditor")
    approve = Permission.objects.create(app=app, key="invoice.approve", name="Approve invoices")
    read = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    write = Permission.objects.create(app=app, key="invoice.write", name="Write invoices")
    _ = RolePermission.objects.create(role=admin, permission=write)
    _ = RolePermission.objects.create(role=auditor, permission=read)
    _ = RolePermission.objects.create(role=auditor, permission=write)
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantRole.objects.create(grant=grant, role=auditor)
    _ = AccessGrantRole.objects.create(grant=grant, role=admin)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=approve)

    # When: 应用通过静态 Bearer token 查询该用户权限。
    before = timezone.now()
    response = Client().get(
        _permission_url(app.app_key, user.authentik_user_id),
        HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
    )
    after = timezone.now()

    # Then: 响应返回稳定排序、去重权限、当前版本、缓存过期时间, 并写入审计。
    assert response.status_code == HTTPStatus.OK
    payload = _permission_payload(response)
    assert payload["user_id"] == "user-api-active"
    assert payload["app_key"] == "crm-api-active"
    assert payload["roles"] == ["admin", "auditor"]
    assert payload["permissions"] == ["invoice.approve", "invoice.read", "invoice.write"]
    assert payload["version"] == 1
    expires_at = datetime.fromisoformat(payload["expires_at"])
    assert expires_at.tzinfo is not None
    assert before + timedelta(seconds=PERMISSION_QUERY_TTL_SECONDS) <= expires_at
    assert expires_at <= after + timedelta(seconds=PERMISSION_QUERY_TTL_SECONDS)
    audit_log = AuditLog.objects.get(event_type="app_permission_queried")
    assert audit_log.actor_type == "app"
    assert audit_log.actor_id == "crm-api-active"
    assert audit_log.target_type == "user_permission"
    assert audit_log.target_id == "user-api-active:crm-api-active"
    assert audit_log.metadata == {
        "app_key": "crm-api-active",
        "user_id": "user-api-active",
        "version": 1,
        "role_count": 2,
        "permission_count": 3,
        "credential_type": "static_token",
        "credential_id": issue.credential_id,
    }
    assert issue.plaintext_token not in str(audit_log.metadata)


@pytest.mark.parametrize(
    ("user_id", "status", "expected_version"),
    [
        ("user-api-unknown", None, 0),
        ("user-api-disabled", "disabled", 1),
        ("user-api-departed", "departed", 1),
    ],
)
def test_permission_query_returns_empty_for_unknown_disabled_or_departed_user(
    user_id: str,
    status: str | None,
    expected_version: int,
) -> None:
    # Given: 用户不存在或不处于 active 状态。
    app = App.objects.create(app_key=f"{user_id}-app", name=f"{user_id} App")
    issue = StaticTokenService.create_token(app=app, name="integration")
    if status is not None:
        user = UserMirror.objects.create(authentik_user_id=user_id, status=status)
        grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
        permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
        _ = AccessGrantPermission.objects.create(grant=grant, permission=permission)

    # When: 应用查询该 user_id 的权限。
    response = Client().get(
        _permission_url(app.app_key, user_id),
        HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
    )

    # Then: 响应不暴露用户存在性, 只返回空授权结果。
    assert response.status_code == HTTPStatus.OK
    payload = _permission_payload(response)
    assert payload["user_id"] == user_id
    assert payload["roles"] == []
    assert payload["permissions"] == []
    assert payload["version"] == expected_version


@pytest.mark.parametrize(
    ("user_id", "grant_status", "expected_version"),
    [
        ("user-api-revoked", GRANT_STATUS_REVOKED, 2),
        ("user-api-expired", GRANT_STATUS_EXPIRED, 3),
    ],
)
def test_permission_query_returns_empty_for_revoked_or_expired_grant(
    user_id: str,
    grant_status: str,
    expected_version: int,
) -> None:
    # Given: 用户最近授权已撤销或过期。
    user = UserMirror.objects.create(authentik_user_id=user_id)
    app = App.objects.create(app_key=f"{user_id}-app", name=f"{user_id} App")
    issue = StaticTokenService.create_token(app=app, name="integration")
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_PERMANENT,
        status=grant_status,
        is_current=False,
        version=expected_version,
    )
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    _ = AccessGrantPermission.objects.create(grant=grant, permission=permission)

    # When: 应用查询该用户权限。
    response = Client().get(
        _permission_url(app.app_key, user_id),
        HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
    )

    # Then: 响应保留最新版本但不返回任何授权。
    assert response.status_code == HTTPStatus.OK
    payload = _permission_payload(response)
    assert payload["roles"] == []
    assert payload["permissions"] == []
    assert payload["version"] == expected_version


@override_settings(EASYAUTH_PERMISSION_QUERY_CACHE_TTL_SECONDS=PERMISSION_QUERY_TTL_SECONDS)
def test_permission_query_uses_earlier_timed_grant_expiration_when_before_ttl() -> None:
    # Given: 当前有效 timed grant 比默认缓存 TTL 更早过期。
    user = UserMirror.objects.create(authentik_user_id="user-api-timed")
    app = App.objects.create(app_key="timed-api-app", name="Timed API App")
    issue = StaticTokenService.create_token(app=app, name="integration")
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    grant_expires_at = timezone.now() + timedelta(seconds=30)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=grant_expires_at,
    )
    _ = AccessGrantPermission.objects.create(grant=grant, permission=permission)

    # When: 应用查询该用户权限。
    response = Client().get(
        _permission_url(app.app_key, user.authentik_user_id),
        HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
    )

    # Then: expires_at 使用 grant_expires_at, 而不是默认 TTL。
    assert response.status_code == HTTPStatus.OK
    payload = _permission_payload(response)
    assert datetime.fromisoformat(payload["expires_at"]) == grant_expires_at


@pytest.mark.parametrize("ttl_setting", [0, -1, "60", True, False, None])
def test_permission_query_uses_default_ttl_for_invalid_configuration(ttl_setting: object) -> None:
    # Given: 权限查询 TTL 配置为非法值。
    user = UserMirror.objects.create(authentik_user_id="user-api-invalid-ttl")
    app = App.objects.create(app_key="invalid-ttl-api-app", name="Invalid TTL API App")
    issue = StaticTokenService.create_token(app=app, name="integration")

    # When: 应用查询该用户权限。
    with override_settings(EASYAUTH_PERMISSION_QUERY_CACHE_TTL_SECONDS=ttl_setting):
        before = timezone.now()
        response = Client().get(
            _permission_url(app.app_key, user.authentik_user_id),
            HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
        )
        after = timezone.now()

    # Then: 非法 TTL 退回默认 300 秒。
    assert response.status_code == HTTPStatus.OK
    expires_at = datetime.fromisoformat(_permission_payload(response)["expires_at"])
    assert before + timedelta(seconds=300) <= expires_at
    assert expires_at <= after + timedelta(seconds=300)


def test_permission_query_uses_default_ttl_when_no_override_is_configured() -> None:
    # Given: 权限查询 TTL 使用项目默认配置。
    user = UserMirror.objects.create(authentik_user_id="user-api-default-ttl")
    app = App.objects.create(app_key="default-ttl-api-app", name="Default TTL API App")
    issue = StaticTokenService.create_token(app=app, name="integration")

    # When: 应用查询该用户权限。
    before = timezone.now()
    response = Client().get(
        _permission_url(app.app_key, user.authentik_user_id),
        HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
    )
    after = timezone.now()

    # Then: 未覆盖配置时使用默认 300 秒。
    assert response.status_code == HTTPStatus.OK
    expires_at = datetime.fromisoformat(_permission_payload(response)["expires_at"])
    assert before + timedelta(seconds=300) <= expires_at
    assert expires_at <= after + timedelta(seconds=300)


def test_permission_query_rejects_missing_invalid_disabled_and_cross_app_tokens() -> None:
    # Given: 存在有效 token、无效 token、禁用 token、禁用应用 token 和跨应用路径。
    app = App.objects.create(app_key="crm-api-errors", name="CRM API Errors")
    disabled_app = App.objects.create(app_key="disabled-api", name="Disabled API", is_active=False)
    issue = StaticTokenService.create_token(app=app, name="integration")
    disabled_issue = StaticTokenService.create_token(app=app, name="disabled")
    disabled_app_issue = StaticTokenService.create_token(app=disabled_app, name="disabled-app")
    _ = AppStaticToken.objects.filter(id=disabled_issue.credential_id).update(is_active=False)

    # When: 各种无权访问请求命中权限查询接口。
    missing = Client().get(_permission_url(app.app_key, "user-api-errors"))
    invalid = Client().get(
        _permission_url(app.app_key, "user-api-errors"),
        HTTP_AUTHORIZATION=_bearer("eat_invalid"),
    )
    disabled = Client().get(
        _permission_url(app.app_key, "user-api-errors"),
        HTTP_AUTHORIZATION=_bearer(disabled_issue.plaintext_token),
    )
    disabled_app_response = Client().get(
        _permission_url(disabled_app.app_key, "user-api-errors"),
        HTTP_AUTHORIZATION=_bearer(disabled_app_issue.plaintext_token),
    )
    cross_app = Client().get(
        _permission_url("erp-api-errors", "user-api-errors"),
        HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
    )

    # Then: 认证失败返回 401, 应用禁用和跨应用访问返回 403, 且全部使用统一错误结构。
    auth_failed = ErrorCode.AUTHENTICATION_FAILED
    _assert_error(missing, status_code=HTTPStatus.UNAUTHORIZED, code=auth_failed)
    _assert_error(invalid, status_code=HTTPStatus.UNAUTHORIZED, code=auth_failed)
    _assert_error(disabled, status_code=HTTPStatus.UNAUTHORIZED, code=auth_failed)
    _assert_error(
        disabled_app_response,
        status_code=HTTPStatus.FORBIDDEN,
        code=ErrorCode.PERMISSION_DENIED,
    )
    _assert_error(cross_app, status_code=HTTPStatus.FORBIDDEN, code=ErrorCode.PERMISSION_DENIED)


def _permission_url(app_key: str, user_id: str) -> str:
    return f"/api/v1/apps/{app_key}/users/{user_id}/permissions"


def _bearer(token: str) -> str:
    return f"Bearer {token}"


def _permission_payload(response: HttpResponseLike) -> PermissionQueryResponsePayload:
    return {
        "user_id": _json_string(response, "user_id"),
        "app_key": _json_string(response, "app_key"),
        "roles": _json_string_array(response, "roles"),
        "permissions": _json_string_array(response, "permissions"),
        "version": _json_int(response, "version"),
        "expires_at": _json_string(response, "expires_at"),
    }


def _json_string(response: HttpResponseLike, key: str) -> str:
    return _json_field_match(response, key, r'"{key}"\s*:\s*"([^"]*)"')


def _json_string_array(response: HttpResponseLike, key: str) -> list[str]:
    array_content = _json_field_match(response, key, r'"{key}"\s*:\s*\[(.*?)\]')
    return findall(r'"([^"]*)"', array_content)


def _json_int(response: HttpResponseLike, key: str) -> int:
    return int(_json_field_match(response, key, r'"{key}"\s*:\s*(\d+)'))


def _json_field_match(response: HttpResponseLike, key: str, pattern: str) -> str:
    match search(pattern.format(key=escape(key)), _response_body(response)):
        case None:
            raise AssertionError(_response_body(response))
        case result:
            return result.group(1)


def _response_body(response: HttpResponseLike) -> str:
    return response.content.decode()


def _assert_error(response: HttpResponseLike, *, status_code: HTTPStatus, code: ErrorCode) -> None:
    assert response.status_code == status_code
    body = _response_body(response)
    assert search(r'"code"\s*:\s*"' + escape(code.value) + r'"', body) is not None
    assert search(r'"message"\s*:\s*"[^"]*"', body) is not None
    assert search(r'"details"\s*:\s*\{\}', body) is not None
