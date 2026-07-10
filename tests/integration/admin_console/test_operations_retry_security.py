from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final

import pytest
from django.contrib.auth.models import User
from django.test import Client

from easyauth.access_requests.models import (
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_TYPE_CHANGE,
    AccessRequest,
    AccessRequestGroup,
    AccessRequestPermission,
)
from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode
from easyauth.applications.models import App, ApprovalRule, AuthorizationGroup, Permission
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-ops4-retry-security"
ACCESS_REQUESTS_API_URL: Final = "/console/api/v1/operations/access-requests"


def test_retry_grant_requires_authenticated_admin_without_mutating_state() -> None:
    # Given: 未登录访问者准备重试一条 grant_failed 申请。
    client = Client(HTTP_HOST="localhost", raise_request_exception=False)
    target_user = UserMirror.objects.create(authentik_user_id="ops4-retry-anon-target")
    app = App.objects.create(app_key="ops4-retry-anon-app", name="Retry Anonymous CRM")
    access_request = AccessRequest.objects.create(
        user=target_user,
        app=app,
        status=REQUEST_STATUS_GRANT_FAILED,
        reason="授权写入失败",
        idempotency_key="retry-anonymous-user",
        payload_digest="a" * 64,
    )

    # When: 未登录访问者提交 retry-grant。
    response = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "未登录重试"}),
        content_type="application/json",
    )

    # Then: API 拒绝请求, 且不创建授权或审计。
    access_request.refresh_from_db()
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json()["error"]["code"] == ErrorCode.AUTHENTICATION_FAILED
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AccessGrant.objects.filter(user=target_user, app=app).count() == 0
    assert AuditLog.objects.count() == 0


def test_retry_grant_requires_superuser_without_mutating_state() -> None:
    # Given: 普通登录用户准备重试一条 grant_failed 申请。
    client = _logged_in_user("ops4-retry-user", is_superuser=False)
    target_user = UserMirror.objects.create(authentik_user_id="ops4-retry-user-target")
    app = App.objects.create(app_key="ops4-retry-user-app", name="Retry User CRM")
    access_request = AccessRequest.objects.create(
        user=target_user,
        app=app,
        status=REQUEST_STATUS_GRANT_FAILED,
        reason="授权写入失败",
        idempotency_key="retry-non-superuser",
        payload_digest="b" * 64,
    )

    # When: 普通用户提交 retry-grant。
    response = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "普通用户重试"}),
        content_type="application/json",
    )

    # Then: API 拒绝请求, 且不创建授权或审计。
    access_request.refresh_from_db()
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["error"]["code"] == ErrorCode.PERMISSION_DENIED
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AccessGrant.objects.filter(user=target_user, app=app).count() == 0
    assert AuditLog.objects.count() == 0


def test_retry_failed_change_rejects_deleted_group_approval_rule() -> None:
    # Given: grant_failed change 申请重试前, 目标授权组的 ApprovalRule 已被删除。
    client = _logged_in_user("ops4-retry-stale-group-admin", is_superuser=True)
    target_user = UserMirror.objects.create(authentik_user_id="ops4-retry-stale-group-target")
    app = App.objects.create(app_key="ops4-retry-stale-group-app", name="Retry Stale Group")
    current_group = AuthorizationGroup.objects.create(
        app=app,
        key="reader",
        kind="role",
        name="Reader",
    )
    target_group = AuthorizationGroup.objects.create(
        app=app,
        key="writer",
        kind="role",
        name="Writer",
    )
    rule = ApprovalRule.objects.create(
        app=app,
        authorization_group=target_group,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(user=target_user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=current_group,
        expires_at=None,
    )
    access_request = AccessRequest.objects.create(
        user=target_user,
        app=app,
        request_type=REQUEST_TYPE_CHANGE,
        status=REQUEST_STATUS_GRANT_FAILED,
        reason="变更授权写入失败",
        idempotency_key="retry-deleted-group-rule",
        payload_digest="c" * 64,
    )
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=target_group,
    )
    _ = rule.delete()

    # When: 管理员通过 retry API 重试该过期申请。
    response = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "修复后重试"}),
        content_type="application/json",
    )

    # Then: API 返回语义错误, 且当前授权和申请状态不变。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    group_keys = tuple(
        AccessGrantGroup.objects.filter(grant=grant).values_list(
            "authorization_group__key",
            flat=True,
        ),
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["error"]["code"] == ErrorCode.SEMANTIC_VALIDATION_ERROR
    assert group_keys == ("reader",)
    assert grant.version == 1
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AuditLog.objects.count() == 0


def test_retry_failed_change_rejects_retargeted_permission_approval_rule() -> None:
    # Given: grant_failed change 申请重试前, 目标 Permission 的 ApprovalRule 已改绑。
    client = _logged_in_user("ops4-retry-stale-permission-admin", is_superuser=True)
    target_user = UserMirror.objects.create(
        authentik_user_id="ops4-retry-stale-permission-target",
    )
    app = App.objects.create(
        app_key="ops4-retry-stale-permission-app",
        name="Retry Stale Permission",
    )
    current_permission = Permission.objects.create(app=app, key="invoice.read", name="Read")
    target_permission = Permission.objects.create(app=app, key="invoice.write", name="Write")
    other_permission = Permission.objects.create(app=app, key="invoice.audit", name="Audit")
    rule = ApprovalRule.objects.create(
        app=app,
        permission=target_permission,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(user=target_user, app=app)
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=current_permission,
        expires_at=None,
    )
    access_request = AccessRequest.objects.create(
        user=target_user,
        app=app,
        request_type=REQUEST_TYPE_CHANGE,
        status=REQUEST_STATUS_GRANT_FAILED,
        reason="变更授权写入失败",
        idempotency_key="retry-retargeted-permission-rule",
        payload_digest="d" * 64,
    )
    _ = AccessRequestPermission.objects.create(
        access_request=access_request,
        permission=target_permission,
    )
    rule.permission = other_permission
    rule.save(update_fields=["permission"])

    # When: 管理员通过 retry API 重试该过期申请。
    response = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "修复后重试"}),
        content_type="application/json",
    )

    # Then: API 返回语义错误, 且当前授权和申请状态不变。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    permission_keys = tuple(
        AccessGrantPermission.objects.filter(grant=grant).values_list(
            "permission__key",
            flat=True,
        ),
    )
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["error"]["code"] == ErrorCode.SEMANTIC_VALIDATION_ERROR
    assert permission_keys == ("invoice.read",)
    assert grant.version == 1
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AuditLog.objects.count() == 0


def _logged_in_user(username: str, *, is_superuser: bool) -> Client:
    _ = User.objects.create_user(
        username=username,
        password=LOGIN_VALUE,
        is_superuser=is_superuser,
    )
    client = Client(HTTP_HOST="localhost", raise_request_exception=False)
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client
