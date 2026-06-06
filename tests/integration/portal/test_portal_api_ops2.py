from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from json import dumps
from re import search
from typing import Final

import pytest
from django.test import Client
from django.utils import timezone

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_GRANT_APPLIED,
    AccessRequest,
    AccessRequestRole,
)
from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import App, ApprovalRule, Permission, Role, RolePermission
from easyauth.grants.models import AccessGrant, AccessGrantPermission, AccessGrantRole

pytestmark = pytest.mark.django_db

PORTAL_URL: Final = "/portal/"
GRANTS_API_URL: Final = "/portal/api/v1/me/grants"
EXPIRING_API_URL: Final = "/portal/api/v1/me/grants/expiring"
REQUESTS_API_URL: Final = "/portal/api/v1/me/access-requests"


def test_ops2_portal_api_lists_current_and_expiring_grants_for_session_user() -> None:
    # Given: 当前员工有长期、即将过期、暂不提醒授权, 另一个员工也有授权。
    client, user = _logged_in_client("ops2-api-grants-user")
    near_app = _create_grant_with_role_permission(
        user=user,
        app_key="ops2-api-near",
        app_name="即将过期 CRM",
        permission_key="crm.read",
        expires_in_days=7,
    )
    _ = _create_grant_with_role_permission(
        user=user,
        app_key="ops2-api-far",
        app_name="暂不提醒 ERP",
        permission_key="erp.read",
        expires_in_days=21,
    )
    _ = _create_grant_with_role_permission(
        user=user,
        app_key="ops2-api-permanent",
        app_name="长期授权系统",
        permission_key="ops.read",
        expires_in_days=None,
    )
    other_user = UserMirror.objects.create(authentik_user_id="ops2-api-other-user")
    _ = _create_grant_with_role_permission(
        user=other_user,
        app_key="ops2-api-other",
        app_name="其他用户系统",
        permission_key="other.read",
        expires_in_days=7,
    )

    # When: 员工读取当前授权和即将过期授权 API。
    grants_response = client.get(GRANTS_API_URL)
    expiring_response = client.get(EXPIRING_API_URL)

    # Then: 当前授权只包含本人 active grant, 即将过期只包含 14 天内到期授权。
    grants_body = grants_response.content.decode()
    expiring_body = expiring_response.content.decode()
    assert grants_response.status_code == HTTPStatus.OK
    assert expiring_response.status_code == HTTPStatus.OK
    assert near_app.app_key in grants_body
    assert "ops2-api-far" in grants_body
    assert "ops2-api-permanent" in grants_body
    assert "crm.read" in grants_body
    assert "ops2-api-other" not in grants_body
    assert near_app.app_key in expiring_body
    assert "ops2-api-far" not in expiring_body
    assert "ops2-api-permanent" not in expiring_body


def test_ops2_portal_api_lists_access_requests_for_session_user() -> None:
    # Given: 当前员工和其他员工都有申请记录。
    client, user = _logged_in_client("ops2-api-requests-user")
    app = App.objects.create(app_key="ops2-api-requests-app", name="CRM")
    role = Role.objects.create(app=app, key="auditor", name="审计员", requestable=True)
    approved = AccessRequest.objects.create(
        user=user,
        app=app,
        status=REQUEST_STATUS_APPROVED,
        reason="审批已通过",
    )
    applied = AccessRequest.objects.create(
        user=user,
        app=app,
        status=REQUEST_STATUS_GRANT_APPLIED,
        applied_at=timezone.now(),
        reason="已落库",
    )
    _ = AccessRequestRole.objects.create(access_request=approved, role=role)
    _ = AccessRequestRole.objects.create(access_request=applied, role=role)
    other_user = UserMirror.objects.create(authentik_user_id="ops2-api-request-other")
    _ = AccessRequest.objects.create(user=other_user, app=app, reason="不应泄露")

    # When: 员工读取自己的申请 API。
    response = client.get(REQUESTS_API_URL)

    # Then: 响应只包含当前员工申请, 并区分 approved 与 grant_applied。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "审批已通过" in body
    assert "授权已落库, 权限已生效" in body
    assert REQUEST_STATUS_APPROVED in body
    assert REQUEST_STATUS_GRANT_APPLIED in body
    assert "不应泄露" not in body


def test_ops2_portal_api_post_access_request_uses_session_user_and_csrf() -> None:
    # Given: 强制 CSRF 的员工 client 和一个可申请角色。
    client, user = _logged_in_client("ops2-api-submit-user", enforce_csrf_checks=True)
    app = App.objects.create(app_key="ops2-api-submit-app", name="CRM")
    role = Role.objects.create(app=app, key="auditor", name="审计员", requestable=True)
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])
    csrf_token = _extract_csrf_token(client.get(PORTAL_URL).content.decode())
    payload = {
        "app_key": app.app_key,
        "role_keys": [role.key],
        "grant_type": GRANT_TYPE_PERMANENT,
        "grant_expires_at": None,
        "reason": "需要查看客户记录",
    }

    # When: 员工分别无 CSRF token 和带 CSRF token 提交申请 API。
    missing_token = client.post(
        REQUESTS_API_URL,
        data=dumps(payload),
        content_type="application/json",
    )
    accepted = client.post(
        REQUESTS_API_URL,
        data=dumps(payload),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    # Then: 无 token 被拒绝, 合法提交只创建当前员工申请且不直接创建授权。
    access_request = AccessRequest.objects.get(user=user, app=app)
    assert missing_token.status_code == HTTPStatus.FORBIDDEN
    assert accepted.status_code == HTTPStatus.CREATED
    assert AccessRequestRole.objects.get(access_request=access_request).role == role
    assert access_request.reason == "需要查看客户记录"
    assert AccessGrant.objects.count() == 0


def test_ops2_portal_api_rejects_missing_session_and_requester_spoofing() -> None:
    # Given: 登录员工尝试在 JSON 里伪造 requester。
    anonymous = Client()
    client, _user = _logged_in_client("ops2-api-spoof-user")
    app = App.objects.create(app_key="ops2-api-spoof-app", name="CRM")
    role = Role.objects.create(app=app, key="auditor", name="审计员", requestable=True)
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])

    # When: 未登录访问 API, 登录员工提交包含 requester_user_id 的 JSON。
    unauthenticated = anonymous.get(GRANTS_API_URL)
    spoofed = client.post(
        REQUESTS_API_URL,
        data=dumps(
            {
                "app_key": app.app_key,
                "role_keys": [role.key],
                "grant_type": GRANT_TYPE_PERMANENT,
                "grant_expires_at": None,
                "reason": "尝试代提",
                "requester_user_id": "ops2-api-other-user",
            },
        ),
        content_type="application/json",
    )

    # Then: API 使用 session 边界, 不接受请求体伪造 requester。
    assert unauthenticated.status_code == HTTPStatus.UNAUTHORIZED
    assert spoofed.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert AccessRequest.objects.count() == 0


def _logged_in_client(
    authentik_user_id: str,
    *,
    enforce_csrf_checks: bool = False,
) -> tuple[Client, UserMirror]:
    client = Client(enforce_csrf_checks=enforce_csrf_checks)
    user = UserMirror.objects.create(
        authentik_user_id=authentik_user_id,
        name="门户用户",
        status=USER_STATUS_ACTIVE,
    )
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()
    return client, user


def _create_grant_with_role_permission(
    *,
    user: UserMirror,
    app_key: str,
    app_name: str,
    permission_key: str,
    expires_in_days: int | None,
) -> App:
    app = App.objects.create(app_key=app_key, name=app_name)
    role = Role.objects.create(app=app, key="operator", name="操作员")
    permission = Permission.objects.create(app=app, key=permission_key, name=permission_key)
    _ = RolePermission.objects.create(role=role, permission=permission)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_PERMANENT if expires_in_days is None else GRANT_TYPE_TIMED,
        grant_expires_at=(
            None if expires_in_days is None else timezone.now() + timedelta(days=expires_in_days)
        ),
    )
    _ = AccessGrantRole.objects.create(grant=grant, role=role)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=permission)
    return app


def _extract_csrf_token(html: str) -> str:
    match = search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    if match is None:
        raise AssertionError(html)
    return match.group(1)
