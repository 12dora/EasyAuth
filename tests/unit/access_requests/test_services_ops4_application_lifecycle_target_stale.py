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
    AccessRequestGroup,
    AccessRequestPermission,
)
from easyauth.access_requests.services import (
    AccessRequestApplication,
    AccessRequestApplicationError,
    AccessRequestService,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, ApprovalRule, AppScope, AuthorizationGroup, Permission
from easyauth.audit.models import AuditLog
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission

pytestmark = pytest.mark.django_db

type LifecycleRequestType = Literal["renew", "revoke"]

LIFECYCLE_REQUEST_TYPES: Final[tuple[LifecycleRequestType, ...]] = (
    REQUEST_TYPE_RENEW,
    REQUEST_TYPE_REVOKE,
)


@pytest.mark.parametrize("request_type", LIFECYCLE_REQUEST_TYPES)
def test_ops4_apply_approved_lifecycle_request_rejects_deleted_group_approval_rule(
    request_type: LifecycleRequestType,
) -> None:
    # Given: lifecycle 申请审批通过后, 目标 AuthorizationGroup 的 ApprovalRule 被删除。
    user = UserMirror.objects.create(
        authentik_user_id=f"ops4-lifecycle-deleted-group-rule-{request_type}",
    )
    app = App.objects.create(
        app_key=f"ops4-lifecycle-deleted-group-rule-{request_type}",
        name="OPS4 Lifecycle Group Rule",
    )
    keep_group = _authorization_group(app, key="viewer", name="Viewer")
    remove_group = _authorization_group(app, key="operator", name="Operator")
    rule = ApprovalRule.objects.create(
        app=app,
        authorization_group=keep_group,
        approver_userids=["manager-001"],
    )
    current_expires_at = timezone.now() + timedelta(days=3)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
    )
    grant_group = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=keep_group,
        expires_at=_grant_expires_at(request_type, current_expires_at),
    )
    _add_revoke_group_target(request_type, grant=grant, authorization_group=remove_group)
    access_request = _approved_request(
        user=user,
        app=app,
        request_type=request_type,
        grant_type=_grant_type(request_type),
        grant_expires_at=_requested_expires_at(request_type),
    )
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=keep_group,
    )
    _ = rule.delete()

    # When: 审批回调尝试应用失去审批规则的 lifecycle 目标。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 当前授权事实不变, 申请进入 grant_failed。
    grant.refresh_from_db()
    grant_group.refresh_from_db()
    access_request.refresh_from_db()
    group_keys = tuple(
        AccessGrantGroup.objects.filter(grant=grant)
        .order_by("authorization_group__key")
        .values_list("authorization_group__key", flat=True),
    )
    assert group_keys == _expected_group_keys(request_type)
    assert grant_group.expires_at == _grant_expires_at(request_type, current_expires_at)
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
    keep_permission = _scoped_permission(app, key="invoice.read", name="Read")
    remove_permission = _scoped_permission(app, key="invoice.write", name="Write")
    _ = ApprovalRule.objects.create(
        app=app,
        permission=keep_permission,
        approver_userids=["manager-001"],
    )
    current_expires_at = timezone.now() + timedelta(days=3)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
    )
    grant_permission = AccessGrantPermission.objects.create(
        grant=grant,
        permission=keep_permission,
        scope_key="GLOBAL",
        expires_at=_grant_expires_at(request_type, current_expires_at),
    )
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
        scope_key="GLOBAL",
    )
    keep_permission.is_active = False
    keep_permission.save(update_fields=["is_active"])

    # When: 审批回调尝试应用被停用的 direct Permission 目标。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 当前授权事实不变, 申请进入 grant_failed。
    grant.refresh_from_db()
    grant_permission.refresh_from_db()
    access_request.refresh_from_db()
    permission_targets = tuple(
        AccessGrantPermission.objects.filter(grant=grant)
        .order_by("permission__key", "scope_key")
        .values_list("permission__key", "scope_key"),
    )
    assert permission_targets == _expected_permission_targets(request_type)
    assert grant_permission.expires_at == _grant_expires_at(request_type, current_expires_at)
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
        idempotency_key=f"{app.app_key}-approved-{request_type}",
        payload_digest="0" * 64,
        approved_at=timezone.now(),
    )


def _application(access_request: AccessRequest) -> AccessRequestApplication:
    return AccessRequestApplication(
        request_id=access_request.id,
        actor_type="approval",
        actor_id="dingtalk-callback",
    )


def _authorization_group(app: App, *, key: str, name: str) -> AuthorizationGroup:
    return AuthorizationGroup.objects.create(app=app, key=key, kind="role", name=name)


def _scoped_permission(app: App, *, key: str, name: str) -> Permission:
    _ = AppScope.objects.get_or_create(app=app, key="GLOBAL", defaults={"name": "Global"})
    return Permission.objects.create(
        app=app,
        key=key,
        name=name,
        supported_scopes=["GLOBAL"],
    )


def _add_revoke_group_target(
    request_type: LifecycleRequestType,
    *,
    grant: AccessGrant,
    authorization_group: AuthorizationGroup,
) -> None:
    match request_type:
        case "renew":
            return
        case "revoke":
            _ = AccessGrantGroup.objects.create(
                grant=grant,
                authorization_group=authorization_group,
                expires_at=None,
            )


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
            _ = AccessGrantPermission.objects.create(
                grant=grant,
                permission=permission,
                scope_key="GLOBAL",
                expires_at=None,
            )


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


def _expected_group_keys(request_type: LifecycleRequestType) -> tuple[str, ...]:
    match request_type:
        case "renew":
            return ("viewer",)
        case "revoke":
            return ("operator", "viewer")


def _expected_permission_targets(request_type: LifecycleRequestType) -> tuple[tuple[str, str], ...]:
    match request_type:
        case "renew":
            return (("invoice.read", "GLOBAL"),)
        case "revoke":
            return (("invoice.read", "GLOBAL"), ("invoice.write", "GLOBAL"))
