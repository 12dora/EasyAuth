from __future__ import annotations

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_TYPE_CHANGE,
    AccessRequest,
    AccessRequestPermission,
    AccessRequestRole,
)
from easyauth.access_requests.services import (
    AccessRequestApplication,
    AccessRequestApplicationError,
    AccessRequestService,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, ApprovalRule, Permission, Role
from easyauth.audit.models import AuditLog
from easyauth.grants.models import AccessGrant, AccessGrantPermission, AccessGrantRole

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("stale_role_field", ["is_active", "requestable"])
def test_ops4_apply_approved_change_rejects_stale_role_target(
    stale_role_field: str,
) -> None:
    # Given: change 申请审批通过后, 目标 Role 的可申请配置被停用。
    user = UserMirror.objects.create(authentik_user_id=f"ops4-stale-role-{stale_role_field}")
    app = App.objects.create(
        app_key=f"ops4-stale-role-{stale_role_field}",
        name="OPS4 Stale Role Target",
    )
    current_role = Role.objects.create(app=app, key="reader", name="Reader")
    target_role = Role.objects.create(app=app, key="writer", name="Writer")
    _ = ApprovalRule.objects.create(app=app, role=target_role, approver_userids=["manager-001"])
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantRole.objects.create(grant=grant, role=current_role)
    access_request = _approved_request(user=user, app=app)
    _ = AccessRequestRole.objects.create(access_request=access_request, role=target_role)
    setattr(target_role, stale_role_field, False)
    target_role.save(update_fields=[stale_role_field])

    # When: 审批回调尝试应用该过期目标。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 授权事实不变, 申请进入 grant_failed。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    role_keys = tuple(
        AccessGrantRole.objects.filter(grant=grant).values_list("role__key", flat=True),
    )
    assert role_keys == ("reader",)
    assert grant.version == 1
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


def test_ops4_apply_approved_change_rejects_stale_permission_target() -> None:
    # Given: change 申请审批通过后, 目标 direct Permission 被停用。
    user = UserMirror.objects.create(authentik_user_id="ops4-stale-permission-target")
    app = App.objects.create(
        app_key="ops4-stale-permission-target",
        name="OPS4 Stale Permission Target",
    )
    current_permission = Permission.objects.create(app=app, key="invoice.read", name="Read")
    target_permission = Permission.objects.create(app=app, key="invoice.write", name="Write")
    _ = ApprovalRule.objects.create(
        app=app,
        permission=target_permission,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=current_permission)
    access_request = _approved_request(user=user, app=app)
    _ = AccessRequestPermission.objects.create(
        access_request=access_request,
        permission=target_permission,
    )
    target_permission.is_active = False
    target_permission.save(update_fields=["is_active"])

    # When: 审批回调尝试应用该过期目标。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 授权事实不变, 申请进入 grant_failed。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    permission_keys = tuple(
        AccessGrantPermission.objects.filter(grant=grant).values_list("permission__key", flat=True),
    )
    assert permission_keys == ("invoice.read",)
    assert grant.version == 1
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


def test_ops4_apply_approved_change_rejects_stale_approval_rule() -> None:
    # Given: change 申请审批通过后, 目标 Role 的 ApprovalRule 被停用。
    user = UserMirror.objects.create(authentik_user_id="ops4-stale-approval-rule")
    app = App.objects.create(app_key="ops4-stale-approval-rule", name="OPS4 Stale Rule")
    current_role = Role.objects.create(app=app, key="reader", name="Reader")
    target_role = Role.objects.create(app=app, key="writer", name="Writer")
    rule = ApprovalRule.objects.create(
        app=app,
        role=target_role,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantRole.objects.create(grant=grant, role=current_role)
    access_request = _approved_request(user=user, app=app)
    _ = AccessRequestRole.objects.create(access_request=access_request, role=target_role)
    rule.is_active = False
    rule.save(update_fields=["is_active"])

    # When: 审批回调尝试应用该过期规则。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 授权事实不变, 申请进入 grant_failed。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    role_keys = tuple(
        AccessGrantRole.objects.filter(grant=grant).values_list("role__key", flat=True),
    )
    assert role_keys == ("reader",)
    assert grant.version == 1
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


def test_ops4_apply_approved_change_rejects_deleted_role_approval_rule() -> None:
    # Given: change 申请审批通过后, 目标 Role 的 ApprovalRule 被删除。
    user = UserMirror.objects.create(authentik_user_id="ops4-deleted-role-rule")
    app = App.objects.create(app_key="ops4-deleted-role-rule", name="OPS4 Deleted Rule")
    current_role = Role.objects.create(app=app, key="reader", name="Reader")
    target_role = Role.objects.create(app=app, key="writer", name="Writer")
    rule = ApprovalRule.objects.create(app=app, role=target_role, approver_userids=["manager-001"])
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantRole.objects.create(grant=grant, role=current_role)
    access_request = _approved_request(user=user, app=app)
    _ = AccessRequestRole.objects.create(access_request=access_request, role=target_role)
    _ = rule.delete()

    # When: 审批回调尝试应用失去审批规则的目标。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 授权事实不变, 申请进入 grant_failed。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    role_keys = tuple(
        AccessGrantRole.objects.filter(grant=grant).values_list("role__key", flat=True),
    )
    assert role_keys == ("reader",)
    assert grant.version == 1
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


def test_ops4_apply_approved_change_rejects_retargeted_permission_approval_rule() -> None:
    # Given: change 申请审批通过后, 目标 Permission 的 ApprovalRule 被改到其他权限。
    user = UserMirror.objects.create(authentik_user_id="ops4-retarget-permission-rule")
    app = App.objects.create(
        app_key="ops4-retarget-permission-rule",
        name="OPS4 Retarget Rule",
    )
    current_permission = Permission.objects.create(app=app, key="invoice.read", name="Read")
    target_permission = Permission.objects.create(app=app, key="invoice.write", name="Write")
    other_permission = Permission.objects.create(app=app, key="invoice.audit", name="Audit")
    rule = ApprovalRule.objects.create(
        app=app,
        permission=target_permission,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=current_permission)
    access_request = _approved_request(user=user, app=app)
    _ = AccessRequestPermission.objects.create(
        access_request=access_request,
        permission=target_permission,
    )
    rule.permission = other_permission
    rule.save(update_fields=["permission"])

    # When: 审批回调尝试应用失去审批规则的权限目标。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 授权事实不变, 申请进入 grant_failed。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    permission_keys = tuple(
        AccessGrantPermission.objects.filter(grant=grant).values_list("permission__key", flat=True),
    )
    assert permission_keys == ("invoice.read",)
    assert grant.version == 1
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


def _approved_request(*, user: UserMirror, app: App) -> AccessRequest:
    return AccessRequest.objects.create(
        user=user,
        app=app,
        request_type=REQUEST_TYPE_CHANGE,
        status=REQUEST_STATUS_APPROVED,
        grant_type=GRANT_TYPE_PERMANENT,
        grant_expires_at=None,
        reason="审批已通过",
        approved_at=timezone.now(),
    )


def _application(access_request: AccessRequest) -> AccessRequestApplication:
    return AccessRequestApplication(
        request_id=access_request.id,
        actor_type="approval",
        actor_id="dingtalk-callback",
    )
