from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_TYPE_CHANGE,
    REQUEST_TYPE_RENEW,
    REQUEST_TYPE_REVOKE,
    AccessRequest,
    AccessRequestRole,
)
from easyauth.access_requests.services import (
    AccessRequestApplication,
    AccessRequestApplicationError,
    AccessRequestService,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, ApprovalRule, Permission, Role, RolePermission
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    GRANT_STATUS_REVOKED,
    AccessGrant,
    AccessGrantRole,
)
from easyauth.grants.query import resolve_user_permissions

pytestmark = pytest.mark.django_db

INITIAL_VERSION, APPLIED_VERSION = 1, 2


def test_ops4_apply_approved_change_request_replaces_grant_roles_and_version() -> None:
    # Given: 审批已通过的 change 申请指向新的角色集合。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-change-user")
    app = App.objects.create(app_key="ops4-apply-change-app", name="OPS4 Apply Change")
    old_role = Role.objects.create(app=app, key="reader", name="Reader")
    new_role = Role.objects.create(app=app, key="writer", name="Writer")
    permission = Permission.objects.create(app=app, key="invoice.write", name="Invoice Write")
    _ = RolePermission.objects.create(role=new_role, permission=permission)
    _ = ApprovalRule.objects.create(app=app, role=new_role, approver_userids=["manager-001"])
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantRole.objects.create(grant=grant, role=old_role)
    access_request = _approved_request(user=user, app=app, request_type=REQUEST_TYPE_CHANGE)
    _ = AccessRequestRole.objects.create(access_request=access_request, role=new_role)

    # When: 审批回调应用该申请。
    applied = AccessRequestService.apply_approved_access_request(
        AccessRequestApplication(
            request_id=access_request.id,
            actor_type="approval",
            actor_id="dingtalk-callback",
        ),
    )

    # Then: 当前授权事实完成替换, version 递增, 权限查询可见新角色权限。
    grant.refresh_from_db()
    snapshot = resolve_user_permissions(user=user, app=app)
    assert applied.status == REQUEST_STATUS_GRANT_APPLIED
    assert grant.version == APPLIED_VERSION
    assert snapshot.version == APPLIED_VERSION
    assert snapshot.roles == ("writer",)
    assert snapshot.permissions == ("invoice.write",)
    assert AuditLog.objects.filter(event_type="grant_changed").count() == 1


def test_ops4_apply_approved_full_revoke_request_revokes_grant_and_query_is_empty() -> None:
    # Given: 审批已通过的空目标 revoke 申请表示全量撤销。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-revoke-user")
    app = App.objects.create(app_key="ops4-apply-revoke-app", name="OPS4 Apply Revoke")
    role = Role.objects.create(app=app, key="reader", name="Reader")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantRole.objects.create(grant=grant, role=role)
    access_request = _approved_request(user=user, app=app, request_type=REQUEST_TYPE_REVOKE)

    # When: 审批回调应用撤销申请。
    applied = AccessRequestService.apply_approved_access_request(
        AccessRequestApplication(
            request_id=access_request.id,
            actor_type="approval",
            actor_id="dingtalk-callback",
        ),
    )

    # Then: 授权被撤销且权限查询返回空集合, 但保留最新 version。
    grant.refresh_from_db()
    snapshot = resolve_user_permissions(user=user, app=app)
    assert applied.status == REQUEST_STATUS_GRANT_APPLIED
    assert grant.status == GRANT_STATUS_REVOKED
    assert grant.is_current is False
    assert grant.version == APPLIED_VERSION
    assert snapshot.version == APPLIED_VERSION
    assert snapshot.roles == ()
    assert snapshot.permissions == ()


def test_ops4_apply_partial_revoke_reduces_roles_and_preserves_expiration() -> None:
    # Given: 审批已通过的 revoke 申请保留当前授权的一部分角色。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-partial-revoke-user")
    app = App.objects.create(
        app_key="ops4-apply-partial-revoke-app",
        name="OPS4 Apply Partial Revoke",
    )
    keep_role = Role.objects.create(app=app, key="viewer", name="Viewer")
    remove_role = Role.objects.create(app=app, key="operator", name="Operator")
    keep_permission = Permission.objects.create(app=app, key="invoice.view", name="Invoice View")
    _ = RolePermission.objects.create(role=keep_role, permission=keep_permission)
    _ = ApprovalRule.objects.create(app=app, role=keep_role, approver_userids=["manager-001"])
    current_expires_at = timezone.now() + timedelta(days=3)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=current_expires_at,
    )
    _ = AccessGrantRole.objects.create(grant=grant, role=keep_role)
    _ = AccessGrantRole.objects.create(grant=grant, role=remove_role)
    access_request = _approved_request(
        user=user,
        app=app,
        request_type=REQUEST_TYPE_REVOKE,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=timezone.now() + timedelta(days=30),
    )
    _ = AccessRequestRole.objects.create(access_request=access_request, role=keep_role)

    # When: 审批回调应用部分撤销申请。
    _ = AccessRequestService.apply_approved_access_request(
        AccessRequestApplication(
            request_id=access_request.id,
            actor_type="approval",
            actor_id="dingtalk-callback",
        ),
    )

    # Then: 授权只保留申请目标角色, 不借 revoke 改变授权期限。
    grant.refresh_from_db()
    snapshot = resolve_user_permissions(user=user, app=app)
    assert grant.status == GRANT_STATUS_ACTIVE
    assert grant.version == APPLIED_VERSION
    assert grant.grant_expires_at == current_expires_at
    assert snapshot.version == APPLIED_VERSION
    assert snapshot.roles == ("viewer",)
    assert snapshot.permissions == ("invoice.view",)


def test_ops4_apply_approved_renew_request_extends_expiration_and_version() -> None:
    # Given: 审批已通过的 renew 申请延长当前限时授权。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-renew-user")
    app = App.objects.create(app_key="ops4-apply-renew-app", name="OPS4 Apply Renew")
    role = Role.objects.create(app=app, key="reader", name="Reader")
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])
    current_expires_at = timezone.now() + timedelta(days=3)
    renewed_expires_at = timezone.now() + timedelta(days=10)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=current_expires_at,
    )
    _ = AccessGrantRole.objects.create(grant=grant, role=role)
    access_request = _approved_request(
        user=user,
        app=app,
        request_type=REQUEST_TYPE_RENEW,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=renewed_expires_at,
    )
    _ = AccessRequestRole.objects.create(access_request=access_request, role=role)

    # When: 审批回调应用续期申请。
    _ = AccessRequestService.apply_approved_access_request(
        AccessRequestApplication(
            request_id=access_request.id,
            actor_type="approval",
            actor_id="dingtalk-callback",
        ),
    )

    # Then: 授权期限和权限查询响应中的 expires_at 都更新为新期限。
    grant.refresh_from_db()
    snapshot = resolve_user_permissions(user=user, app=app)
    assert grant.status == GRANT_STATUS_ACTIVE
    assert grant.version == APPLIED_VERSION
    assert grant.grant_expires_at == renewed_expires_at
    assert snapshot.version == APPLIED_VERSION
    assert snapshot.grant_expires_at == renewed_expires_at


def test_ops4_apply_approved_request_returns_applied_callback_without_reincrementing() -> None:
    # Given: 一条 approved change 申请已经被应用过一次。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-repeat-user")
    app = App.objects.create(app_key="ops4-apply-repeat-app", name="OPS4 Apply Repeat")
    role = Role.objects.create(app=app, key="reader", name="Reader")
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    access_request = _approved_request(user=user, app=app, request_type=REQUEST_TYPE_CHANGE)
    _ = AccessRequestRole.objects.create(access_request=access_request, role=role)
    application = AccessRequestApplication(
        request_id=access_request.id,
        actor_type="approval",
        actor_id="dingtalk-callback",
    )

    # When: 同一回调被重复处理。
    _ = AccessRequestService.apply_approved_access_request(application)
    repeated = AccessRequestService.apply_approved_access_request(application)

    # Then: 重复处理返回已应用申请, 不会再次递增授权版本。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    assert repeated.status == REQUEST_STATUS_GRANT_APPLIED
    assert grant.version == APPLIED_VERSION
    assert access_request.status == REQUEST_STATUS_GRANT_APPLIED
    assert AuditLog.objects.filter(event_type="grant_changed").count() == 1
    assert AuditLog.objects.filter(event_type="access_request_grant_applied").count() == 1


def test_ops4_apply_approved_change_request_without_current_grant_marks_failed() -> None:
    # Given: 生命周期 change 申请审批通过后, 当前授权已不存在。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-stale-change-user")
    app = App.objects.create(app_key="ops4-apply-stale-change-app", name="OPS4 Stale Change")
    role = Role.objects.create(app=app, key="writer", name="Writer")
    access_request = _approved_request(user=user, app=app, request_type=REQUEST_TYPE_CHANGE)
    _ = AccessRequestRole.objects.create(access_request=access_request, role=role)

    # When: 审批回调尝试应用过期的生命周期申请。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(
            AccessRequestApplication(
                request_id=access_request.id,
                actor_type="approval",
                actor_id="dingtalk-callback",
            ),
        )

    # Then: 服务不创建新授权, 申请进入 grant_failed。
    access_request.refresh_from_db()
    assert AccessGrant.objects.filter(user=user, app=app).count() == 0
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


def test_ops4_apply_approved_request_marks_grant_failed_when_grant_service_fails() -> None:
    # Given: approved change 申请包含跨 App 角色, 会在 GrantService 替换授权成员时失败。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-failed-user")
    app = App.objects.create(app_key="ops4-apply-failed-app", name="OPS4 Apply Failed")
    other_app = App.objects.create(
        app_key="ops4-apply-failed-other-app",
        name="OPS4 Apply Failed Other",
    )
    old_role = Role.objects.create(app=app, key="reader", name="Reader")
    bad_role = Role.objects.create(app=other_app, key="writer", name="Writer")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantRole.objects.create(grant=grant, role=old_role)
    access_request = _approved_request(user=user, app=app, request_type=REQUEST_TYPE_CHANGE)
    _ = AccessRequestRole.objects.create(access_request=access_request, role=bad_role)

    # When: 审批回调尝试应用该申请。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(
            AccessRequestApplication(
                request_id=access_request.id,
                actor_type="approval",
                actor_id="dingtalk-callback",
            ),
        )

    # Then: 授权写入回滚, 申请进入 grant_failed 并记录失败审计。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert access_request.applied_at is None
    assert grant.version == INITIAL_VERSION
    assert list(
        AccessGrantRole.objects.filter(grant=grant).values_list("role__key", flat=True),
    ) == ["reader"]
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


def _approved_request(
    *,
    user: UserMirror,
    app: App,
    request_type: str,
    grant_type: str = GRANT_TYPE_PERMANENT,
    grant_expires_at: datetime | None = None,
) -> AccessRequest:
    return AccessRequest.objects.create(
        user=user,
        app=app,
        request_type=request_type,
        status=REQUEST_STATUS_APPROVED,
        grant_type=grant_type,
        grant_expires_at=grant_expires_at,
        reason="审批已通过",
        approved_at=timezone.now(),
    )
