from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    DECISION_ACTOR_USER,
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_GRANT_CONFLICT,
    REQUEST_STATUS_GRANT_EXPIRED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_TYPE_CHANGE,
    REQUEST_TYPE_GRANT,
    REQUEST_TYPE_RENEW,
    REQUEST_TYPE_REVOKE,
    AccessRequest,
    AccessRequestGroup,
    AccessRequestGroupGrantSnapshot,
)
from easyauth.access_requests.services import (
    AccessRequestApplication,
    AccessRequestApplicationError,
    AccessRequestService,
)
from easyauth.accounts.models import UserMirror
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
    GRANT_STATUS_ACTIVE,
    GRANT_STATUS_REVOKED,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from easyauth.grants.query import ExpandedGrant, resolve_user_permissions

pytestmark = pytest.mark.django_db

INITIAL_VERSION, APPLIED_VERSION = 1, 2


def test_ops4_apply_approved_change_request_replaces_grant_groups_and_version() -> None:
    # Given: 审批已通过的 change 申请指向新的授权组集合。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-change-user")
    app = App.objects.create(app_key="ops4-apply-change-app", name="OPS4 Apply Change")
    old_group = _authorization_group(app, key="reader", name="Reader")
    new_group = _authorization_group(app, key="writer", name="Writer")
    permission = _scoped_permission(app, key="invoice.write", name="Invoice Write")
    current_group_grant = AuthorizationGroupGrant.objects.create(
        authorization_group=new_group,
        permission=permission,
        scope_key="GLOBAL",
    )
    approval_rule = ApprovalRule.objects.create(
        app=app,
        authorization_group=new_group,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=old_group,
        expires_at=None,
    )
    access_request = _approved_request(user=user, app=app, request_type=REQUEST_TYPE_CHANGE)
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=new_group,
    )
    _ = _snapshot_group_grant(access_request, new_group, permission)
    current_group_grant.is_active = False
    current_group_grant.save(update_fields=["is_active"])
    approval_rule.is_active = False
    approval_rule.save(update_fields=["is_active"])
    new_group.is_active = False
    new_group.requestable = False
    new_group.save(update_fields=["is_active", "requestable"])
    changed_permission = _scoped_permission(app, key="invoice.admin", name="Invoice Admin")
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=new_group,
        permission=changed_permission,
        scope_key="GLOBAL",
    )

    # When: 审批回调应用该申请。
    applied = AccessRequestService.apply_approved_access_request(
        AccessRequestApplication(
            request_id=access_request.id,
            actor_type="approval",
            actor_id="dingtalk-callback",
        ),
    )

    # Then: 当前授权事实按提交快照完成替换, version 递增, 权限查询不再动态展开当前授权组配置。
    grant.refresh_from_db()
    snapshot = resolve_user_permissions(user=user, app=app)
    assert applied.status == REQUEST_STATUS_GRANT_APPLIED
    assert grant.version == APPLIED_VERSION
    assert snapshot.grant_version == APPLIED_VERSION
    assert AccessGrantGroup.objects.filter(grant=grant).count() == 0
    assert snapshot.groups == ()
    assert snapshot.grants == (
        ExpandedGrant(
            permission="invoice.write",
            scope="GLOBAL",
            source_type="direct",
            source_key="",
            expires_at=None,
        ),
    )
    assert AuditLog.objects.filter(event_type="grant_changed").count() == 1


def test_ops4_apply_approved_full_revoke_request_revokes_grant_and_query_is_empty() -> None:
    # Given: 审批已通过的空目标 revoke 申请表示全量撤销。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-revoke-user")
    app = App.objects.create(app_key="ops4-apply-revoke-app", name="OPS4 Apply Revoke")
    group = _authorization_group(app, key="reader", name="Reader")
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=None,
    )
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
    assert snapshot.grant_version == APPLIED_VERSION
    assert snapshot.groups == ()
    assert snapshot.grants == ()


def test_ops4_apply_partial_revoke_reduces_roles_and_preserves_expiration() -> None:
    # Given: 审批已通过的 revoke 申请保留当前授权的一部分授权组。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-partial-revoke-user")
    app = App.objects.create(
        app_key="ops4-apply-partial-revoke-app",
        name="OPS4 Apply Partial Revoke",
    )
    keep_group = _authorization_group(app, key="viewer", name="Viewer")
    remove_group = _authorization_group(app, key="operator", name="Operator")
    keep_permission = _scoped_permission(app, key="invoice.view", name="Invoice View")
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=keep_group,
        permission=keep_permission,
        scope_key="GLOBAL",
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=keep_group,
        approver_userids=["manager-001"],
    )
    current_expires_at = timezone.now() + timedelta(days=3)
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=keep_group,
        expires_at=current_expires_at,
    )
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=remove_group,
        expires_at=current_expires_at,
    )
    access_request = _approved_request(
        user=user,
        app=app,
        request_type=REQUEST_TYPE_REVOKE,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=timezone.now() + timedelta(days=30),
    )
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=keep_group,
    )
    _ = _snapshot_group_grant(access_request, keep_group, keep_permission)

    # When: 审批回调应用部分撤销申请。
    _ = AccessRequestService.apply_approved_access_request(
        AccessRequestApplication(
            request_id=access_request.id,
            actor_type="approval",
            actor_id="dingtalk-callback",
        ),
    )

    # Then: 授权只保留申请目标授权组, 不借 revoke 改变授权期限。
    grant.refresh_from_db()
    snapshot = resolve_user_permissions(user=user, app=app)
    assert grant.status == GRANT_STATUS_ACTIVE
    assert grant.version == APPLIED_VERSION
    assert AccessGrantGroup.objects.filter(grant=grant).count() == 0
    assert (
        AccessGrantPermission.objects.get(grant=grant, permission=keep_permission).expires_at
        == current_expires_at
    )
    assert snapshot.grant_version == APPLIED_VERSION
    assert snapshot.groups == ()
    assert snapshot.grants == (
        ExpandedGrant("invoice.view", "GLOBAL", "direct", "", current_expires_at),
    )


def test_ops4_apply_approved_renew_request_extends_expiration_and_version() -> None:
    # Given: 审批已通过的 renew 申请延长当前限时授权。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-renew-user")
    app = App.objects.create(app_key="ops4-apply-renew-app", name="OPS4 Apply Renew")
    group = _authorization_group(app, key="reader", name="Reader")
    permission = _scoped_permission(app, key="invoice.view", name="Invoice View")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )
    current_expires_at = timezone.now() + timedelta(days=3)
    renewed_expires_at = timezone.now() + timedelta(days=10)
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=current_expires_at,
    )
    access_request = _approved_request(
        user=user,
        app=app,
        request_type=REQUEST_TYPE_RENEW,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=renewed_expires_at,
    )
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)
    _ = _snapshot_group_grant(access_request, group, permission)

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
    assert AccessGrantGroup.objects.filter(grant=grant).count() == 0
    assert (
        AccessGrantPermission.objects.get(grant=grant, permission=permission).expires_at
        == renewed_expires_at
    )
    assert snapshot.grant_version == APPLIED_VERSION
    assert snapshot.groups == ()
    assert snapshot.grants == (
        ExpandedGrant("invoice.view", "GLOBAL", "direct", "", renewed_expires_at),
    )


def test_ops4_apply_grant_uses_group_snapshot_after_group_deleted() -> None:
    # Given: grant 申请审批通过后, 目标授权组实体被硬删除, live link 已消失。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-deleted-grant-user")
    app = App.objects.create(app_key="ops4-apply-deleted-grant-app", name="OPS4 Deleted Grant")
    group = _authorization_group(app, key="reader", name="Reader")
    permission = _scoped_permission(app, key="invoice.read", name="Invoice Read")
    access_request = _approved_request(user=user, app=app, request_type=REQUEST_TYPE_GRANT)
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)
    _ = _snapshot_group_grant(access_request, group, permission)
    _ = group.delete()

    # When: 审批回调应用该申请。
    _ = AccessRequestService.apply_approved_access_request(
        AccessRequestApplication(
            request_id=access_request.id,
            actor_type="approval",
            actor_id="dingtalk-callback",
        ),
    )

    # Then: 落地仍只使用提交快照, 不依赖已被 CASCADE 删除的 AccessRequestGroup。
    access_request.refresh_from_db()
    grant = AccessGrant.objects.get(user=user, app=app)
    snapshot = resolve_user_permissions(user=user, app=app)
    assert access_request.status == REQUEST_STATUS_GRANT_APPLIED
    assert AccessRequestGroup.objects.filter(access_request=access_request).count() == 0
    assert AccessGrantGroup.objects.filter(grant=grant).count() == 0
    assert snapshot.grants == (
        ExpandedGrant("invoice.read", "GLOBAL", "direct", "", None),
    )


def test_ops4_apply_change_uses_group_snapshot_after_target_group_deleted() -> None:
    # Given: change 申请审批通过后, 新目标授权组实体被硬删除, live link 已消失。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-deleted-change-user")
    app = App.objects.create(app_key="ops4-apply-deleted-change-app", name="OPS4 Deleted Change")
    old_group = _authorization_group(app, key="reader", name="Reader")
    new_group = _authorization_group(app, key="writer", name="Writer")
    permission = _scoped_permission(app, key="invoice.write", name="Invoice Write")
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=old_group)
    access_request = _approved_request(user=user, app=app, request_type=REQUEST_TYPE_CHANGE)
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=new_group,
    )
    _ = _snapshot_group_grant(access_request, new_group, permission)
    _ = new_group.delete()

    # When: 审批回调应用该申请。
    _ = AccessRequestService.apply_approved_access_request(
        AccessRequestApplication(
            request_id=access_request.id,
            actor_type="approval",
            actor_id="dingtalk-callback",
        ),
    )

    # Then: 当前授权按冻结快照替换为 direct grant, 不读取已删除 group 或 link。
    access_request.refresh_from_db()
    grant.refresh_from_db()
    snapshot = resolve_user_permissions(user=user, app=app)
    assert access_request.status == REQUEST_STATUS_GRANT_APPLIED
    assert grant.version == APPLIED_VERSION
    assert AccessRequestGroup.objects.filter(access_request=access_request).count() == 0
    assert AccessGrantGroup.objects.filter(grant=grant).count() == 0
    assert snapshot.grants == (
        ExpandedGrant("invoice.write", "GLOBAL", "direct", "", None),
    )


def test_ops4_apply_renew_deleted_target_group_enters_conflict_not_empty_mutation() -> None:
    # Given: renew 申请审批通过后, 当前目标授权组被硬删除, base grant 成员事实已漂移。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-deleted-renew-user")
    app = App.objects.create(app_key="ops4-apply-deleted-renew-app", name="OPS4 Deleted Renew")
    group = _authorization_group(app, key="reader", name="Reader")
    permission = _scoped_permission(app, key="invoice.read", name="Invoice Read")
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=timezone.now() + timedelta(days=3),
    )
    access_request = _approved_request(
        user=user,
        app=app,
        request_type=REQUEST_TYPE_RENEW,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=timezone.now() + timedelta(days=10),
    )
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)
    _ = _snapshot_group_grant(access_request, group, permission)
    _ = group.delete()

    # When: 审批回调尝试应用该申请。
    with pytest.raises(AccessRequestApplicationError) as exc_info:
        _ = AccessRequestService.apply_approved_access_request(
            AccessRequestApplication(
                request_id=access_request.id,
                actor_type="approval",
                actor_id="dingtalk-callback",
            ),
        )

    # Then: 申请进入 grant_conflict, 不会按空目标执行或产生空 mutation。
    access_request.refresh_from_db()
    grant.refresh_from_db()
    assert exc_info.value.kind == "base_revision_conflict"
    assert access_request.status == REQUEST_STATUS_GRANT_CONFLICT
    assert grant.status == GRANT_STATUS_ACTIVE
    assert grant.version == INITIAL_VERSION
    assert AccessGrantPermission.objects.filter(grant=grant).count() == 0


def test_ops4_apply_partial_revoke_deleted_target_group_conflicts_not_full_revoke() -> None:
    # Given: partial revoke 申请保留的目标授权组被硬删除, live link 已消失。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-deleted-revoke-user")
    app = App.objects.create(app_key="ops4-apply-deleted-revoke-app", name="OPS4 Deleted Revoke")
    keep_group = _authorization_group(app, key="viewer", name="Viewer")
    remove_group = _authorization_group(app, key="operator", name="Operator")
    keep_permission = _scoped_permission(app, key="invoice.view", name="Invoice View")
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=keep_group)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=remove_group)
    access_request = _approved_request(user=user, app=app, request_type=REQUEST_TYPE_REVOKE)
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=keep_group,
    )
    _ = _snapshot_group_grant(access_request, keep_group, keep_permission)
    _ = keep_group.delete()

    # When: 审批回调尝试应用该申请。
    with pytest.raises(AccessRequestApplicationError) as exc_info:
        _ = AccessRequestService.apply_approved_access_request(
            AccessRequestApplication(
                request_id=access_request.id,
                actor_type="approval",
                actor_id="dingtalk-callback",
            ),
        )

    # Then: 冻结目标仍被识别为非空, 申请冲突退出, 不会误走 full revoke。
    access_request.refresh_from_db()
    grant.refresh_from_db()
    assert exc_info.value.kind == "base_revision_conflict"
    assert access_request.status == REQUEST_STATUS_GRANT_CONFLICT
    assert grant.status == GRANT_STATUS_ACTIVE
    assert grant.is_current is True
    assert grant.version == INITIAL_VERSION
    assert tuple(
        AccessGrantGroup.objects.filter(grant=grant).values_list(
            "authorization_group__key",
            flat=True,
        ),
    ) == ("operator",)


def test_ops4_apply_approved_request_returns_applied_callback_without_reincrementing() -> None:
    # Given: 一条 approved change 申请已经被应用过一次。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-repeat-user")
    app = App.objects.create(app_key="ops4-apply-repeat-app", name="OPS4 Apply Repeat")
    group = _authorization_group(app, key="reader", name="Reader")
    permission = _scoped_permission(app, key="invoice.view", name="Invoice View")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=None,
    )
    access_request = _approved_request(user=user, app=app, request_type=REQUEST_TYPE_CHANGE)
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)
    _ = _snapshot_group_grant(access_request, group, permission)
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


def test_ops4_apply_approved_change_request_fails_when_base_revision_changed() -> None:
    # Given: 申请基于授权 v1 审批, 但落地前当前授权已被其他命令推进到 v2。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-revision-conflict-user")
    app = App.objects.create(app_key="ops4-apply-revision-conflict-app", name="OPS4 Revision")
    old_group = _authorization_group(app, key="reader", name="Reader")
    new_group = _authorization_group(app, key="writer", name="Writer")
    other_group = _authorization_group(app, key="auditor", name="Auditor")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=new_group,
        approver_userids=["manager-001"],
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=old_group)
    access_request = _approved_request(user=user, app=app, request_type=REQUEST_TYPE_CHANGE)
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=new_group,
    )
    grant.version += 1
    grant.save(update_fields=["version", "updated_at"])
    _ = AccessGrantGroup.objects.filter(grant=grant).delete()
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=other_group)

    # When: 审批回调尝试应用旧 revision 的决定。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(
            AccessRequestApplication(
                request_id=access_request.id,
                actor_type="approval",
                actor_id="dingtalk-callback",
            ),
        )

    # Then: 申请进入不可重试的 revision 冲突终态, 当前 v2 授权事实不被旧决定覆盖。
    access_request.refresh_from_db()
    grant.refresh_from_db()
    assert access_request.status == REQUEST_STATUS_GRANT_CONFLICT
    assert grant.version == APPLIED_VERSION
    assert tuple(
        AccessGrantGroup.objects.filter(grant=grant).values_list(
            "authorization_group__key",
            flat=True,
        ),
    ) == ("auditor",)
    assert AuditLog.objects.filter(event_type="grant_apply_conflict").count() == 1


@pytest.mark.parametrize("request_type", [REQUEST_TYPE_CHANGE, REQUEST_TYPE_RENEW])
def test_ops4_apply_expired_timed_request_preserves_current_grant(request_type: str) -> None:
    # Given: 已通过的限时 change/renew 申请在授权应用前已经到期。
    user = UserMirror.objects.create(
        authentik_user_id=f"ops4-expired-{request_type}-user",
    )
    app = App.objects.create(
        app_key=f"ops4-expired-{request_type}-app",
        name=f"OPS4 Expired {request_type.title()}",
    )
    group = _authorization_group(app, key="reader", name="Reader")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )
    current_expires_at = timezone.now() + timedelta(days=3)
    grant = AccessGrant.objects.create(user=user, app=app)
    grant_group = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=current_expires_at,
    )
    access_request = _approved_request(
        user=user,
        app=app,
        request_type=request_type,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=timezone.now() - timedelta(minutes=1),
    )
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=group,
    )
    grant_id = grant.id
    grant_group_id = cast("int", grant_group.pk)
    grant_before = AccessGrant.objects.filter(id=grant_id).values().get()
    grant_group_before = AccessGrantGroup.objects.filter(id=grant_group_id).values().get()

    # When: 审批回调尝试应用已到期的申请。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(
            AccessRequestApplication(
                request_id=access_request.id,
                actor_type="approval",
                actor_id="dingtalk-callback",
            ),
        )

    # Then: 旧授权事实完全不变, 申请标记为到期且只记录对应审计。
    access_request.refresh_from_db()
    assert AccessGrant.objects.filter(id=grant_id).values().get() == grant_before
    assert AccessGrantGroup.objects.filter(id=grant_group_id).values().get() == grant_group_before
    assert access_request.status == REQUEST_STATUS_GRANT_EXPIRED
    assert access_request.applied_at is None
    assert list(AuditLog.objects.values_list("event_type", flat=True)) == [
        "grant_expired_before_apply",
    ]


def test_ops4_apply_approved_change_request_without_current_grant_marks_failed() -> None:
    # Given: 生命周期 change 申请审批通过后, 当前授权已不存在。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-stale-change-user")
    app = App.objects.create(app_key="ops4-apply-stale-change-app", name="OPS4 Stale Change")
    group = _authorization_group(app, key="writer", name="Writer")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )
    stale_grant = AccessGrant.objects.create(
        user=user,
        app=app,
        status=GRANT_STATUS_REVOKED,
        is_current=False,
    )
    access_request = _approved_request(
        user=user,
        app=app,
        request_type=REQUEST_TYPE_CHANGE,
        base_grant=stale_grant,
    )
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)

    # When: 审批回调尝试应用过期的生命周期申请。
    with pytest.raises(AccessRequestApplicationError):
        _ = AccessRequestService.apply_approved_access_request(
            AccessRequestApplication(
                request_id=access_request.id,
                actor_type="approval",
                actor_id="dingtalk-callback",
            ),
        )

    # Then: 服务不创建新授权, 申请进入不可重试的 base grant 冲突终态。
    access_request.refresh_from_db()
    assert AccessGrant.objects.filter(user=user, app=app, is_current=True).count() == 0
    assert access_request.status == REQUEST_STATUS_GRANT_CONFLICT
    assert AuditLog.objects.filter(event_type="grant_apply_conflict").count() == 1


def test_ops4_apply_approved_request_marks_grant_failed_when_grant_service_fails() -> None:
    # Given: approved change 申请的 App 在审批后失效, 落地必需实体校验会失败。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-failed-user")
    app = App.objects.create(app_key="ops4-apply-failed-app", name="OPS4 Apply Failed")
    old_group = _authorization_group(app, key="reader", name="Reader")
    bad_group = _authorization_group(app, key="writer", name="Writer")
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=old_group,
        expires_at=None,
    )
    access_request = _approved_request(user=user, app=app, request_type=REQUEST_TYPE_CHANGE)
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=bad_group,
    )
    app.is_active = False
    app.save(update_fields=["is_active"])

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
        AccessGrantGroup.objects.filter(grant=grant).values_list(
            "authorization_group__key",
            flat=True,
        ),
    ) == ["reader"]
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


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


def _snapshot_group_grant(
    access_request: AccessRequest,
    group: AuthorizationGroup,
    permission: Permission,
) -> AccessRequestGroupGrantSnapshot:
    return AccessRequestGroupGrantSnapshot.objects.create(
        access_request=access_request,
        authorization_group_id_snapshot=group.id,
        authorization_group_key=group.key,
        authorization_group_kind=group.kind,
        authorization_group_name=group.name,
        permission_key=permission.key,
        permission_name=permission.name,
        scope_key="GLOBAL",
    )


def _approved_request(  # noqa: PLR0913
    *,
    user: UserMirror,
    app: App,
    request_type: str,
    grant_type: str = GRANT_TYPE_PERMANENT,
    grant_expires_at: datetime | None = None,
    base_grant: AccessGrant | None = None,
) -> AccessRequest:
    if request_type != "grant" and base_grant is None:
        base_grant = AccessGrant.objects.get(user=user, app=app, is_current=True)
    decided_at = timezone.now()
    return AccessRequest.objects.create(
        user=user,
        app=app,
        request_type=request_type,
        status=REQUEST_STATUS_APPROVED,
        grant_type=grant_type,
        grant_expires_at=grant_expires_at,
        reason="审批已通过",
        idempotency_key=f"ops4-approved-{user.authentik_user_id}-{request_type}",
        payload_digest="0" * 64,
        base_grant=base_grant,
        base_grant_revision=base_grant.version if base_grant is not None else None,
        approved_at=decided_at,
        decided_at=decided_at,
        decided_by="approver",
        decision_actor_type=DECISION_ACTOR_USER,
    )
