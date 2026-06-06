from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final, Literal

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_TYPE_RENEW,
    REQUEST_TYPE_REVOKE,
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

type LifecycleRequestType = Literal["renew", "revoke"]

LIFECYCLE_REQUEST_TYPES: Final[tuple[LifecycleRequestType, ...]] = (
    REQUEST_TYPE_RENEW,
    REQUEST_TYPE_REVOKE,
)


@pytest.mark.parametrize("request_type", LIFECYCLE_REQUEST_TYPES)
def test_ops4_apply_approved_lifecycle_request_rejects_deleted_role_approval_rule(
    request_type: LifecycleRequestType,
) -> None:
    # Given: lifecycle 申请审批通过后, 目标 Role 的 ApprovalRule 被删除。
    user = UserMirror.objects.create(
        authentik_user_id=f"ops4-lifecycle-deleted-role-rule-{request_type}",
    )
    app = App.objects.create(
        app_key=f"ops4-lifecycle-deleted-role-rule-{request_type}",
        name="OPS4 Lifecycle Role Rule",
    )
    keep_role = Role.objects.create(app=app, key="viewer", name="Viewer")
    remove_role = Role.objects.create(app=app, key="operator", name="Operator")
    rule = ApprovalRule.objects.create(app=app, role=keep_role, approver_userids=["manager-001"])
    current_expires_at = timezone.now() + timedelta(days=3)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=_grant_type(request_type),
        grant_expires_at=_grant_expires_at(request_type, current_expires_at),
    )
    _ = AccessGrantRole.objects.create(grant=grant, role=keep_role)
    _add_revoke_role_target(request_type, grant=grant, role=remove_role)
    access_request = _approved_request(
        user=user,
        app=app,
        request_type=request_type,
        grant_type=_grant_type(request_type),
        grant_expires_at=_requested_expires_at(request_type),
    )
    _ = AccessRequestRole.objects.create(access_request=access_request, role=keep_role)
    _ = rule.delete()

    # When: 审批回调尝试应用失去审批规则的 lifecycle 目标。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 当前授权事实不变, 申请进入 grant_failed。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    role_keys = tuple(
        AccessGrantRole.objects.filter(grant=grant)
        .order_by("role__key")
        .values_list("role__key", flat=True),
    )
    assert role_keys == _expected_role_keys(request_type)
    assert grant.grant_expires_at == _grant_expires_at(request_type, current_expires_at)
    assert grant.version == 1
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert access_request.applied_at is None
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


@pytest.mark.parametrize("request_type", LIFECYCLE_REQUEST_TYPES)
def test_ops4_apply_approved_lifecycle_request_rejects_inactive_direct_permission(
    request_type: LifecycleRequestType,
) -> None:
    # Given: lifecycle 申请审批通过后, 目标 direct Permission 被停用。
    user = UserMirror.objects.create(
        authentik_user_id=f"ops4-lifecycle-inactive-permission-{request_type}",
    )
    app = App.objects.create(
        app_key=f"ops4-lifecycle-inactive-permission-{request_type}",
        name="OPS4 Lifecycle Permission",
    )
    keep_permission = Permission.objects.create(app=app, key="invoice.read", name="Read")
    remove_permission = Permission.objects.create(app=app, key="invoice.write", name="Write")
    _ = ApprovalRule.objects.create(
        app=app,
        permission=keep_permission,
        approver_userids=["manager-001"],
    )
    current_expires_at = timezone.now() + timedelta(days=3)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=_grant_type(request_type),
        grant_expires_at=_grant_expires_at(request_type, current_expires_at),
    )
    _ = AccessGrantPermission.objects.create(grant=grant, permission=keep_permission)
    _add_revoke_permission_target(request_type, grant=grant, permission=remove_permission)
    access_request = _approved_request(
        user=user,
        app=app,
        request_type=request_type,
        grant_type=_grant_type(request_type),
        grant_expires_at=_requested_expires_at(request_type),
    )
    _ = AccessRequestPermission.objects.create(
        access_request=access_request,
        permission=keep_permission,
    )
    keep_permission.is_active = False
    keep_permission.save(update_fields=["is_active"])

    # When: 审批回调尝试应用被停用的 direct Permission 目标。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 当前授权事实不变, 申请进入 grant_failed。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    permission_keys = tuple(
        AccessGrantPermission.objects.filter(grant=grant)
        .order_by("permission__key")
        .values_list("permission__key", flat=True),
    )
    assert permission_keys == _expected_permission_keys(request_type)
    assert grant.grant_expires_at == _grant_expires_at(request_type, current_expires_at)
    assert grant.version == 1
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert access_request.applied_at is None
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


def _approved_request(
    *,
    user: UserMirror,
    app: App,
    request_type: LifecycleRequestType,
    grant_type: str,
    grant_expires_at: datetime | None,
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


def _application(access_request: AccessRequest) -> AccessRequestApplication:
    return AccessRequestApplication(
        request_id=access_request.id,
        actor_type="approval",
        actor_id="dingtalk-callback",
    )


def _add_revoke_role_target(
    request_type: LifecycleRequestType,
    *,
    grant: AccessGrant,
    role: Role,
) -> None:
    match request_type:
        case "renew":
            return
        case "revoke":
            _ = AccessGrantRole.objects.create(grant=grant, role=role)


def _add_revoke_permission_target(
    request_type: LifecycleRequestType,
    *,
    grant: AccessGrant,
    permission: Permission,
) -> None:
    match request_type:
        case "renew":
            return
        case "revoke":
            _ = AccessGrantPermission.objects.create(grant=grant, permission=permission)


def _grant_type(request_type: LifecycleRequestType) -> str:
    match request_type:
        case "renew":
            return GRANT_TYPE_TIMED
        case "revoke":
            return GRANT_TYPE_PERMANENT


def _grant_expires_at(
    request_type: LifecycleRequestType,
    current_expires_at: datetime,
) -> datetime | None:
    match request_type:
        case "renew":
            return current_expires_at
        case "revoke":
            return None


def _requested_expires_at(request_type: LifecycleRequestType) -> datetime | None:
    match request_type:
        case "renew":
            return timezone.now() + timedelta(days=10)
        case "revoke":
            return None


def _expected_role_keys(request_type: LifecycleRequestType) -> tuple[str, ...]:
    match request_type:
        case "renew":
            return ("viewer",)
        case "revoke":
            return ("operator", "viewer")


def _expected_permission_keys(request_type: LifecycleRequestType) -> tuple[str, ...]:
    match request_type:
        case "renew":
            return ("invoice.read",)
        case "revoke":
            return ("invoice.read", "invoice.write")
