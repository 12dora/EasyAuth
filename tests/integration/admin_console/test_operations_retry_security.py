from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from easyauth.access_requests.models import (
    DECISION_ACTOR_CONSOLE_ADMIN,
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_TYPE_CHANGE,
    AccessRequest,
    AccessRequestGroup,
    AccessRequestGroupGrantSnapshot,
    AccessRequestPermission,
)
from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode
from easyauth.applications.models import (
    App,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    authenticate_console_user,
)

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-ops4-retry-security"
ACCESS_REQUESTS_API_URL: Final = "/console/api/v1/operations/access-requests"
RETRIED_GRANT_VERSION: Final = 2


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
        approved_at=timezone.now(),
        decided_at=timezone.now(),
        decided_by="ops4-retry-anon-admin",
        decision_actor_type=DECISION_ACTOR_CONSOLE_ADMIN,
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
        approved_at=timezone.now(),
        decided_at=timezone.now(),
        decided_by="ops4-retry-user-admin",
        decision_actor_type=DECISION_ACTOR_CONSOLE_ADMIN,
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
        base_grant=grant,
        base_grant_revision=1,
        reason="变更授权写入失败",
        idempotency_key="retry-deleted-group-rule",
        payload_digest="c" * 64,
        approved_at=timezone.now(),
        decided_at=timezone.now(),
        decided_by="ops4-retry-stale-group-admin",
        decision_actor_type=DECISION_ACTOR_CONSOLE_ADMIN,
    )
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=target_group,
    )
    _attach_group_snapshot(access_request, target_group)
    _ = rule.delete()

    # When: 管理员通过 retry API 重试该过期申请。
    response = client.post(
        f"{ACCESS_REQUESTS_API_URL}/{access_request.id}/retry-grant",
        data=dumps({"reason": "修复后重试"}),
        content_type="application/json",
    )

    # Then: retry 只使用提交时冻结的授权组展开事实, 不再依赖当前 ApprovalRule。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    group_count = AccessGrantGroup.objects.filter(grant=grant).count()
    direct_grants = tuple(
        AccessGrantPermission.objects.filter(grant=grant).values_list(
            "permission__key",
            "scope_key",
        ),
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()["status"] == REQUEST_STATUS_GRANT_APPLIED
    assert group_count == 0
    assert direct_grants == (("writer.read", "writer-scope"),)
    assert grant.version == RETRIED_GRANT_VERSION
    assert access_request.status == REQUEST_STATUS_GRANT_APPLIED
    assert AuditLog.objects.filter(event_type="access_request_grant_retry_applied").count() == 1


def test_retry_failed_change_applies_retargeted_permission_approval_rule_request() -> None:
    # Given: grant_failed change 申请重试前, 目标 Permission 的 ApprovalRule 已改绑。
    client = _logged_in_user("ops4-retry-stale-permission-admin", is_superuser=True)
    target_user = UserMirror.objects.create(
        authentik_user_id="ops4-retry-stale-permission-target",
    )
    app = App.objects.create(
        app_key="ops4-retry-stale-permission-app",
        name="Retry Stale Permission",
    )
    scope = AppScope.objects.create(app=app, key="GLOBAL", name="Global")
    current_permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Read",
        supported_scopes=[scope.key],
    )
    target_permission = Permission.objects.create(
        app=app,
        key="invoice.write",
        name="Write",
        supported_scopes=[scope.key],
    )
    other_permission = Permission.objects.create(
        app=app,
        key="invoice.audit",
        name="Audit",
        supported_scopes=[scope.key],
    )
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
        base_grant=grant,
        base_grant_revision=1,
        reason="变更授权写入失败",
        idempotency_key="retry-retargeted-permission-rule",
        payload_digest="d" * 64,
        approved_at=timezone.now(),
        decided_at=timezone.now(),
        decided_by="ops4-retry-stale-permission-admin",
        decision_actor_type=DECISION_ACTOR_CONSOLE_ADMIN,
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

    # Then: retry 使用已审批的申请事实, 不再重新依赖当前 ApprovalRule 绑定。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    direct_grants = tuple(
        AccessGrantPermission.objects.filter(grant=grant).values_list(
            "permission__key",
            "scope_key",
        ),
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()["status"] == REQUEST_STATUS_GRANT_APPLIED
    assert direct_grants == (("invoice.write", "GLOBAL"),)
    assert grant.version == RETRIED_GRANT_VERSION
    assert access_request.status == REQUEST_STATUS_GRANT_APPLIED
    assert AuditLog.objects.filter(event_type="access_request_grant_retry_applied").count() == 1


def _logged_in_user(username: str, *, is_superuser: bool) -> Client:
    _ = User.objects.create_user(
        username=username,
        password=LOGIN_VALUE,
        is_superuser=is_superuser,
    )
    client = Client(HTTP_HOST="localhost", raise_request_exception=False)
    if is_superuser:
        _ = authenticate_console_admin(client, username)
    else:
        _ = authenticate_console_user(client, username)
    return client


def _attach_group_snapshot(access_request: AccessRequest, group: AuthorizationGroup) -> None:
    scope = AppScope.objects.create(app=access_request.app, key=f"{group.key}-scope", name="Scope")
    permission = Permission.objects.create(
        app=access_request.app,
        key=f"{group.key}.read",
        name=f"{group.name} Read",
        supported_scopes=[scope.key],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key=scope.key,
    )
    _ = AccessRequestGroupGrantSnapshot.objects.create(
        access_request=access_request,
        authorization_group_id_snapshot=group.id,
        authorization_group_key=group.key,
        authorization_group_kind=group.kind,
        authorization_group_name=group.name,
        permission_key=permission.key,
        permission_name=permission.name,
        scope_key=scope.key,
    )
