from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from json import dumps
from re import findall, search
from typing import Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from easyauth.access_requests.models import REQUEST_STATUS_SUBMITTED, AccessRequest
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.applications.services import StaticTokenService
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    GRANT_STATUS_REVOKED,
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    AccessGrant,
    AccessGrantGroup,
)

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-ops3"
ACCESS_REQUESTS_API_URL: Final = "/console/api/v1/operations/access-requests"
ACCESS_GRANTS_API_URL: Final = "/console/api/v1/operations/access-grants"
EMERGENCY_REVOKES_API_URL: Final = "/console/api/v1/operations/emergency-revokes"
AUDIT_LOGS_API_URL: Final = "/console/api/v1/audit-logs"


class HttpResponseLike(Protocol):
    status_code: int
    content: bytes


def test_ops3_access_requests_supports_time_range_and_pagination() -> None:
    # Given: 系统管理员面对不同创建时间的授权申请。
    client = _logged_in_superuser("ops3-request-filter-admin")
    user = UserMirror.objects.create(authentik_user_id="ops3-request-filter-user")
    app = App.objects.create(app_key="ops3-request-filter-app", name="CRM")
    old_request = AccessRequest.objects.create(
        user=user,
        app=app,
        status=REQUEST_STATUS_SUBMITTED,
        reason="旧申请",
    )
    new_request = AccessRequest.objects.create(
        user=user,
        app=app,
        status=REQUEST_STATUS_SUBMITTED,
        reason="新申请",
    )
    now = timezone.now()
    _ = AccessRequest.objects.filter(id=old_request.id).update(submitted_at=now - timedelta(days=3))
    _ = AccessRequest.objects.filter(id=new_request.id).update(submitted_at=now)

    # When: 管理员按 created_from 和分页读取申请。
    response = client.get(
        ACCESS_REQUESTS_API_URL,
        {
            "created_from": (now - timedelta(hours=1)).isoformat(),
            "page": "1",
            "page_size": "1",
        },
    )

    # Then: 响应只包含时间范围内的当前页记录并返回分页信息。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "新申请" in body
    assert "旧申请" not in body
    assert _json_int(response, "page") == 1
    assert _json_int(response, "page_size") == 1
    assert _json_int(response, "total_items") == 1


def test_ops3_access_grants_supports_version_current_revoked_and_expiration_filters() -> None:
    # Given: 系统管理员面对不同版本、当前状态和过期时间的授权。
    client = _logged_in_superuser("ops3-grant-filter-admin")
    user = UserMirror.objects.create(authentik_user_id="ops3-grant-filter-user")
    app = App.objects.create(app_key="ops3-grant-filter-app", name="CRM")
    soon = timezone.now() + timedelta(days=1)
    later = timezone.now() + timedelta(days=10)
    _ = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    revoked = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=soon,
        status=GRANT_STATUS_REVOKED,
        is_current=False,
        version=2,
    )
    other_user = UserMirror.objects.create(authentik_user_id="ops3-grant-filter-other")
    _ = AccessGrant.objects.create(
        user=other_user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=later,
        version=2,
    )

    # When: 管理员组合 version、current、revoked 和 expires_before 过滤授权。
    response = client.get(
        ACCESS_GRANTS_API_URL,
        {
            "version": "2",
            "current": "false",
            "revoked": "true",
            "expires_before": (timezone.now() + timedelta(days=2)).isoformat(),
            "page": "1",
            "page_size": "10",
        },
    )

    # Then: 只返回符合全部运营筛选条件的授权。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert str(revoked.id) in body
    assert "ops3-grant-filter-other" not in body
    assert _json_int(response, "total_items") == 1


def test_ops3_audit_logs_supports_target_time_range_and_pagination() -> None:
    # Given: 系统管理员需要定位某个 target 的审计事件。
    client = _logged_in_superuser("ops3-audit-filter-admin")
    _ = AuditLog.objects.create(
        actor_type="admin",
        actor_id="security",
        event_type="grant_revoked",
        target_type="user_app",
        target_id="old-target",
        metadata={"app_key": "ops3-audit-filter-app"},
    )
    now = timezone.now()
    _ = AuditLog.objects.create(
        actor_type="admin",
        actor_id="security",
        event_type="grant_revoked",
        target_type="user_app",
        target_id="current-target",
        metadata={"app_key": "ops3-audit-filter-app"},
    )

    # When: 管理员按 target_id、created_from 和分页查询审计日志。
    response = client.get(
        AUDIT_LOGS_API_URL,
        {
            "target_id": "current-target",
            "created_from": (now - timedelta(hours=1)).isoformat(),
            "page": "1",
            "page_size": "1",
        },
    )

    # Then: 响应只返回匹配 target 和时间范围的审计日志。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "current-target" in body
    assert "old-target" not in body
    assert _json_int(response, "total_items") == 1


def test_ops3_emergency_revoke_removes_public_permission_query_result() -> None:
    # Given: 应用 token 可查询用户当前授权权限。
    admin_client = _logged_in_superuser("ops3-public-revoke-admin")
    target_user = UserMirror.objects.create(authentik_user_id="ops3-public-revoke-target")
    app = App.objects.create(app_key="ops3-public-revoke-app", name="Emergency CRM")
    _ = AppScope.objects.create(app=app, key="SELF", name="Self")
    issue = StaticTokenService.create_token(app=app, name="CRM integration")
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Read invoices",
        supported_scopes=["SELF"],
    )
    group = AuthorizationGroup.objects.create(app=app, key="auditor", kind="role", name="Auditor")
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key="SELF",
    )
    grant = AccessGrant.objects.create(
        user=target_user,
        app=app,
        grant_type=GRANT_TYPE_PERMANENT,
    )
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=group)

    # When: 管理员紧急撤权后, 应用再次调用公共权限查询 API。
    revoke_response = admin_client.post(
        EMERGENCY_REVOKES_API_URL,
        data=dumps(
            {
                "user_id": target_user.authentik_user_id,
                "app_key": app.app_key,
                "reason": "安全事件应急",
            },
        ),
        content_type="application/json",
    )
    permission_response = Client().get(
        f"/api/v1/apps/{app.app_key}/users/{target_user.authentik_user_id}/permissions",
        HTTP_AUTHORIZATION=f"Bearer {issue.plaintext_token}",
    )

    # Then: 撤权成功, 公共权限查询返回空授权组和空授权明细。
    grant.refresh_from_db()
    assert revoke_response.status_code == HTTPStatus.OK
    assert permission_response.status_code == HTTPStatus.OK
    assert _json_string_array(permission_response, "groups") == []
    assert _json_string_array(permission_response, "grants") == []
    assert _json_int(permission_response, "grant_version") == grant.version


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _json_int(response: HttpResponseLike, key: str) -> int:
    return int(_json_field_match(response, key, r'"{key}"\s*:\s*(\d+)'))


def _json_string_array(response: HttpResponseLike, key: str) -> list[str]:
    array_content = _json_field_match(response, key, r'"{key}"\s*:\s*\[(.*?)\]')
    return findall(r'"([^"]*)"', array_content)


def _json_field_match(response: HttpResponseLike, key: str, pattern: str) -> str:
    match = search(pattern.format(key=key), response.content.decode())
    if match is None:
        raise AssertionError(response.content.decode())
    return match.group(1)
