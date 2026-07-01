from __future__ import annotations

from typing import Literal

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_TYPE_CHANGE,
    REQUEST_TYPE_GRANT,
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


@pytest.mark.parametrize("stale_group_field", ["is_active", "requestable"])
def test_ops4_apply_approved_change_rejects_stale_authorization_group_target(
    stale_group_field: str,
) -> None:
    # Given: change 申请审批通过后, 目标 AuthorizationGroup 的可申请配置被停用。
    user = UserMirror.objects.create(authentik_user_id=f"ops4-stale-group-{stale_group_field}")
    app = App.objects.create(
        app_key=f"ops4-stale-group-{stale_group_field}",
        name="OPS4 Stale Group Target",
    )
    current_group = _authorization_group(app, key="reader", name="Reader")
    target_group = _authorization_group(app, key="writer", name="Writer")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=target_group,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=current_group)
    access_request = _approved_request(user=user, app=app)
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=target_group,
    )
    setattr(target_group, stale_group_field, False)
    target_group.save(update_fields=[stale_group_field])

    # When: 审批回调尝试应用该过期目标。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 授权事实不变, 申请进入 grant_failed。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    group_keys = tuple(
        AccessGrantGroup.objects.filter(grant=grant).values_list(
            "authorization_group__key",
            flat=True,
        ),
    )
    assert group_keys == ("reader",)
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
    current_permission = _scoped_permission(app, key="invoice.read", name="Read")
    target_permission = _scoped_permission(app, key="invoice.write", name="Write")
    _ = ApprovalRule.objects.create(
        app=app,
        permission=target_permission,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=current_permission,
        scope_key="GLOBAL",
    )
    access_request = _approved_request(user=user, app=app)
    _ = AccessRequestPermission.objects.create(
        access_request=access_request,
        permission=target_permission,
        scope_key="GLOBAL",
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
        AccessGrantPermission.objects.filter(grant=grant).values_list(
            "permission__key",
            "scope_key",
        ),
    )
    assert permission_keys == (("invoice.read", "GLOBAL"),)
    assert grant.version == 1
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


@pytest.mark.parametrize(
    "stale_target",
    ["permission_active", "permission_deprecated", "scope_active", "permission_rule"],
)
def test_ops4_apply_approved_grant_rejects_stale_direct_permission_target(
    stale_target: Literal[
        "permission_active",
        "permission_deprecated",
        "scope_active",
        "permission_rule",
    ],
) -> None:
    # Given: grant 申请审批通过后, 目标 direct Permission 配置失效。
    user = UserMirror.objects.create(authentik_user_id=f"ops4-stale-grant-{stale_target}")
    app = App.objects.create(
        app_key=f"ops4-stale-grant-{stale_target}",
        name="OPS4 Stale Grant Permission",
    )
    scope = AppScope.objects.create(app=app, key="GLOBAL", name="Global")
    target_permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Read",
        supported_scopes=[scope.key],
    )
    rule = ApprovalRule.objects.create(
        app=app,
        permission=target_permission,
        approver_userids=["manager-001"],
    )
    access_request = _approved_request(
        user=user,
        app=app,
        request_type=REQUEST_TYPE_GRANT,
    )
    _ = AccessRequestPermission.objects.create(
        access_request=access_request,
        permission=target_permission,
        scope_key=scope.key,
    )
    match stale_target:
        case "permission_active":
            target_permission.is_active = False
            target_permission.save(update_fields=["is_active"])
        case "permission_deprecated":
            target_permission.deprecated_at = timezone.now()
            target_permission.deprecated_reason = "改用 invoice.v2.read"
            target_permission.save(update_fields=["deprecated_at", "deprecated_reason"])
        case "scope_active":
            scope.is_active = False
            scope.save(update_fields=["is_active"])
        case "permission_rule":
            rule.is_active = False
            rule.save(update_fields=["is_active"])

    # When: 审批回调尝试应用该过期 direct Permission。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 授权事实不创建, 申请进入 grant_failed。
    access_request.refresh_from_db()
    assert AccessGrant.objects.count() == 0
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


def test_ops4_apply_approved_change_rejects_stale_authorization_group_approval_rule() -> None:
    # Given: change 申请审批通过后, 目标 AuthorizationGroup 的 ApprovalRule 被停用。
    user = UserMirror.objects.create(authentik_user_id="ops4-stale-approval-rule")
    app = App.objects.create(app_key="ops4-stale-approval-rule", name="OPS4 Stale Rule")
    current_group = _authorization_group(app, key="reader", name="Reader")
    target_group = _authorization_group(app, key="writer", name="Writer")
    rule = ApprovalRule.objects.create(
        app=app,
        authorization_group=target_group,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=current_group)
    access_request = _approved_request(user=user, app=app)
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=target_group,
    )
    rule.is_active = False
    rule.save(update_fields=["is_active"])

    # When: 审批回调尝试应用该过期规则。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 授权事实不变, 申请进入 grant_failed。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    group_keys = tuple(
        AccessGrantGroup.objects.filter(grant=grant).values_list(
            "authorization_group__key",
            flat=True,
        ),
    )
    assert group_keys == ("reader",)
    assert grant.version == 1
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


def test_ops4_apply_approved_change_rejects_deleted_authorization_group_approval_rule() -> None:
    # Given: change 申请审批通过后, 目标 AuthorizationGroup 的 ApprovalRule 被删除。
    user = UserMirror.objects.create(authentik_user_id="ops4-deleted-group-rule")
    app = App.objects.create(app_key="ops4-deleted-group-rule", name="OPS4 Deleted Rule")
    current_group = _authorization_group(app, key="reader", name="Reader")
    target_group = _authorization_group(app, key="writer", name="Writer")
    rule = ApprovalRule.objects.create(
        app=app,
        authorization_group=target_group,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=current_group)
    access_request = _approved_request(user=user, app=app)
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=target_group,
    )
    _ = rule.delete()

    # When: 审批回调尝试应用失去审批规则的目标。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(_application(access_request))

    # Then: 授权事实不变, 申请进入 grant_failed。
    grant.refresh_from_db()
    access_request.refresh_from_db()
    group_keys = tuple(
        AccessGrantGroup.objects.filter(grant=grant).values_list(
            "authorization_group__key",
            flat=True,
        ),
    )
    assert group_keys == ("reader",)
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
    current_permission = _scoped_permission(app, key="invoice.read", name="Read")
    target_permission = _scoped_permission(app, key="invoice.write", name="Write")
    other_permission = _scoped_permission(app, key="invoice.audit", name="Audit")
    rule = ApprovalRule.objects.create(
        app=app,
        permission=target_permission,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=current_permission,
        scope_key="GLOBAL",
    )
    access_request = _approved_request(user=user, app=app)
    _ = AccessRequestPermission.objects.create(
        access_request=access_request,
        permission=target_permission,
        scope_key="GLOBAL",
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
        AccessGrantPermission.objects.filter(grant=grant).values_list(
            "permission__key",
            "scope_key",
        ),
    )
    assert permission_keys == (("invoice.read", "GLOBAL"),)
    assert grant.version == 1
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


def _approved_request(
    *,
    user: UserMirror,
    app: App,
    request_type: str = REQUEST_TYPE_CHANGE,
) -> AccessRequest:
    return AccessRequest.objects.create(
        user=user,
        app=app,
        request_type=request_type,
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
