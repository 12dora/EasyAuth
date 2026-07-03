from __future__ import annotations

from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Final, Protocol

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, override_settings
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode
from easyauth.applications.models import (
    App,
    AppScope,
    AppStaticToken,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.applications.services import StaticTokenService
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    GRANT_STATUS_EXPIRED,
    GRANT_STATUS_REVOKED,
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)

pytestmark = pytest.mark.django_db

PERMISSION_QUERY_TTL_SECONDS: Final = 120
ACTIVE_APP_CATALOG_VERSION: Final = 12
EMPTY_APP_CATALOG_VERSION: Final = 7


class HttpResponseLike(Protocol):
    status_code: int
    content: bytes

    def json(self) -> dict[str, object]: ...


@override_settings(EASYAUTH_PERMISSION_QUERY_CACHE_TTL_SECONDS=PERMISSION_QUERY_TTL_SECONDS)
def test_permission_query_returns_groups_grants_versions_expiration_and_audit() -> None:
    # Given: 应用静态 token 绑定了当前应用, 用户有当前有效授权。
    user = UserMirror.objects.create(authentik_user_id="user-api-active")
    app = App.objects.create(
        app_key="crm-api-active",
        name="CRM API Active",
        catalog_version=ACTIVE_APP_CATALOG_VERSION,
    )
    _scope(app, "SELF")
    _scope(app, "TEAM")
    issue = StaticTokenService.create_token(app=app, name="CRM integration")
    sales = AuthorizationGroup.objects.create(app=app, key="sales", kind="role", name="销售")
    finance = AuthorizationGroup.objects.create(app=app, key="finance", kind="bundle", name="财务")
    approve = _permission(app, "invoice.approve", scopes=["TEAM"])
    read = _permission(app, "invoice.read", scopes=["SELF"])
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=sales,
        permission=read,
        scope_key="SELF",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=finance,
        permission=approve,
        scope_key="TEAM",
    )
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=sales)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=finance)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=approve, scope_key="TEAM")

    # When: 应用通过静态 Bearer token 查询该用户权限。
    before = timezone.now()
    response = Client().get(
        _permission_url(app.app_key, user.authentik_user_id),
        HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
    )
    after = timezone.now()

    # Then: 响应返回新版快照结构和审计 metadata。
    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["user_id"] == "user-api-active"
    assert payload["app_key"] == "crm-api-active"
    assert payload["groups"] == [
        {"key": "finance", "kind": "bundle", "name": "财务"},
        {"key": "sales", "kind": "role", "name": "销售"},
    ]
    assert payload["grants"] == [
        {
            "permission": "invoice.approve",
            "scope": "TEAM",
            "source_type": "direct",
            "source_key": "",
        },
        {
            "permission": "invoice.approve",
            "scope": "TEAM",
            "source_type": "group",
            "source_key": "finance",
        },
        {
            "permission": "invoice.read",
            "scope": "SELF",
            "source_type": "group",
            "source_key": "sales",
        },
    ]
    assert payload["grant_version"] == 1
    assert payload["catalog_version"] == ACTIVE_APP_CATALOG_VERSION
    assert payload["snapshot_version"] == "1.12"
    expires_at = datetime.fromisoformat(str(payload["expires_at"]))
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
        "group_count": 2,
        "grant_count": 3,
        "grant_version": 1,
        "catalog_version": ACTIVE_APP_CATALOG_VERSION,
        "snapshot_version": "1.12",
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
    app = App.objects.create(
        app_key=f"{user_id}-app",
        name=f"{user_id} App",
        catalog_version=EMPTY_APP_CATALOG_VERSION,
    )
    _scope(app, "SELF")
    issue = StaticTokenService.create_token(app=app, name="integration")
    if status is not None:
        user = UserMirror.objects.create(authentik_user_id=user_id, status=status)
        grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
        permission = _permission(app, "invoice.read", scopes=["SELF"])
        _ = AccessGrantPermission.objects.create(
            grant=grant,
            permission=permission,
            scope_key="SELF",
        )

    # When: 应用查询该 user_id 的权限。
    response = Client().get(
        _permission_url(app.app_key, user_id),
        HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
    )

    # Then: 响应不暴露用户存在性, 只返回空授权结果。
    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["user_id"] == user_id
    assert payload["groups"] == []
    assert payload["grants"] == []
    assert payload["grant_version"] == expected_version
    assert payload["catalog_version"] == EMPTY_APP_CATALOG_VERSION
    assert payload["snapshot_version"] == f"{expected_version}.{EMPTY_APP_CATALOG_VERSION}"


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
    _scope(app, "SELF")
    issue = StaticTokenService.create_token(app=app, name="integration")
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_PERMANENT,
        status=grant_status,
        is_current=False,
        version=expected_version,
    )
    permission = _permission(app, "invoice.read", scopes=["SELF"])
    _ = AccessGrantPermission.objects.create(grant=grant, permission=permission, scope_key="SELF")

    # When: 应用查询该用户权限。
    response = Client().get(
        _permission_url(app.app_key, user_id),
        HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
    )

    # Then: 响应保留最新版本但不返回任何授权。
    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["groups"] == []
    assert payload["grants"] == []
    assert payload["grant_version"] == expected_version


@override_settings(EASYAUTH_PERMISSION_QUERY_CACHE_TTL_SECONDS=PERMISSION_QUERY_TTL_SECONDS)
def test_permission_query_uses_earlier_timed_grant_expiration_when_before_ttl() -> None:
    # Given: 当前有效 timed grant 比默认缓存 TTL 更早过期。
    user = UserMirror.objects.create(authentik_user_id="user-api-timed")
    app = App.objects.create(app_key="timed-api-app", name="Timed API App")
    _scope(app, "SELF")
    issue = StaticTokenService.create_token(app=app, name="integration")
    permission = _permission(app, "invoice.read", scopes=["SELF"])
    grant_expires_at = timezone.now() + timedelta(seconds=30)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=grant_expires_at,
    )
    _ = AccessGrantPermission.objects.create(grant=grant, permission=permission, scope_key="SELF")

    # When: 应用查询该用户权限。
    response = Client().get(
        _permission_url(app.app_key, user.authentik_user_id),
        HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
    )

    # Then: expires_at 使用 grant_expires_at, 而不是默认 TTL。
    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert datetime.fromisoformat(str(payload["expires_at"])) == grant_expires_at


@pytest.mark.parametrize("ttl_setting", [0, -1, "60", True, False, None])
def test_permission_query_fails_fast_for_invalid_ttl_configuration(ttl_setting: object) -> None:
    # Given: 权限查询 TTL 配置为非法值。
    user = UserMirror.objects.create(authentik_user_id="user-api-invalid-ttl")
    app = App.objects.create(app_key="invalid-ttl-api-app", name="Invalid TTL API App")
    issue = StaticTokenService.create_token(app=app, name="integration")

    # When / Then: 配置错误必须显式失败, 不允许静默退回默认 TTL 延长撤销窗口。
    with (
        override_settings(EASYAUTH_PERMISSION_QUERY_CACHE_TTL_SECONDS=ttl_setting),
        pytest.raises(ImproperlyConfigured),
    ):
        _ = Client().get(
            _permission_url(app.app_key, user.authentik_user_id),
            HTTP_AUTHORIZATION=_bearer(issue.plaintext_token),
        )


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
    expires_at = datetime.fromisoformat(str(response.json()["expires_at"]))
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


def _scope(app: App, key: str, *, is_active: bool = True) -> AppScope:
    return AppScope.objects.create(app=app, key=key, name=key.title(), is_active=is_active)


def _permission(app: App, key: str, *, scopes: list[str]) -> Permission:
    return Permission.objects.create(app=app, key=key, name=key, supported_scopes=scopes)


def _assert_error(response: HttpResponseLike, *, status_code: HTTPStatus, code: ErrorCode) -> None:
    assert response.status_code == status_code
    payload = response.json()["error"]
    assert payload["code"] == code.value
    assert isinstance(payload["message"], str)
    assert payload["details"] == {}
