from __future__ import annotations

import pytest

from easyauth.access_requests.models import GRANT_TYPE_PERMANENT, AccessRequest, AccessRequestGroup
from easyauth.access_requests.services import (
    AccessRequestService,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
)
from easyauth.access_requests.submission_types import ScopedAccessRequestGrant
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
from easyauth.grants.models import AccessGrant

pytestmark = pytest.mark.django_db


def _ensure_active_approver() -> str:
    # 审批人必须是活跃系统用户且不能是申请人本人; 用固定的第二用户满足该不变量。
    approver, _ = UserMirror.objects.get_or_create(authentik_user_id="approver-001")
    return approver.authentik_user_id


def test_s14_submit_grant_request_rejects_inactive_app_without_writes() -> None:
    # Given: 一个员工选择了停用应用中的授权组。
    user = UserMirror.objects.create(authentik_user_id="s14-service-inactive-app-user")
    app = App.objects.create(
        app_key="s14-service-inactive-app",
        name="S14 Inactive App",
        is_active=False,
    )
    group = AuthorizationGroup.objects.create(app=app, key="admin", kind="role", name="CRM 管理员")

    # When / Then: 服务拒绝提交, 不落库申请、授权或审计。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_grant_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                authorization_groups=(group,),
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=None,
                reason="停用应用不应提交",
                actor_type="user",
                actor_id=user.authentik_user_id,
                idempotency_key="s14-reject-inactive-app",
            ),
        )

    assert "app is not active" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0
    assert AccessGrant.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_s14_submit_grant_request_rejects_empty_targets_without_writes() -> None:
    # Given: 一个员工没有选择任何授权组或 direct grant。
    user = UserMirror.objects.create(authentik_user_id="s14-service-empty-role-user")
    app = App.objects.create(app_key="s14-service-empty-role", name="S14 Empty Role")

    # When / Then: 服务拒绝提交, 不落库申请、授权或审计。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_grant_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=None,
                reason="未选择角色不应提交",
                actor_type="user",
                actor_id=user.authentik_user_id,
                idempotency_key="s14-reject-empty-targets",
            ),
        )

    assert "at least one authorization group or direct grant" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0
    assert AccessGrant.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_s14_submit_grant_request_deduplicates_repeated_groups() -> None:
    # Given: 一个员工重复提交同一个有效授权组。
    user = UserMirror.objects.create(authentik_user_id="s14-service-duplicate-role-user")
    app = App.objects.create(app_key="s14-service-duplicate-role", name="S14 Duplicate Role")
    group = AuthorizationGroup.objects.create(app=app, key="admin", kind="role", name="CRM 管理员")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )

    # When: 服务处理重复授权组输入。
    access_request = AccessRequestService.submit_grant_request(
        AccessRequestSubmission(
            user=user,
            app=app,
            authorization_groups=(group, group),
            grant_type=GRANT_TYPE_PERMANENT,
            grant_expires_at=None,
            reason="重复角色应去重",
            actor_type="user",
            actor_id=user.authentik_user_id,
            idempotency_key="s14-deduplicate-repeated-groups",
            approver_user_ids=(_ensure_active_approver(),),
        ),
    )

    # Then: 只创建一条授权组链接, 审计授权组列表也去重。
    assert AccessRequestGroup.objects.filter(access_request=access_request).count() == 1
    audit_log = AuditLog.objects.get(event_type="access_request_submitted")
    assert audit_log.metadata["authorization_group_keys"] == [group.key]


def test_s14_submit_grant_request_rejects_applicant_as_approver_without_writes() -> None:
    # Given: 申请人把自己填成审批人 (自审自批)。
    user = UserMirror.objects.create(authentik_user_id="s14-self-approver-user")
    app = App.objects.create(app_key="s14-self-approver", name="S14 Self Approver")
    group = AuthorizationGroup.objects.create(app=app, key="admin", kind="role", name="CRM 管理员")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )

    # When / Then: 服务快速失败拒绝, 不落库申请、授权或审计。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_grant_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                authorization_groups=(group,),
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=None,
                reason="自审自批不应通过",
                actor_type="user",
                actor_id=user.authentik_user_id,
                idempotency_key="s14-reject-applicant-as-approver",
                approver_user_ids=(user.authentik_user_id,),
            ),
        )

    assert "approver must not be the applicant" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0
    assert AccessGrant.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_submit_rejects_direct_grant_covered_by_authorization_group() -> None:
    user = UserMirror.objects.create(authentik_user_id="overlap-user")
    approver = UserMirror.objects.create(authentik_user_id="overlap-approver")
    app = App.objects.create(app_key="overlap-app", name="交集校验")
    _ = AppScope.objects.create(app=app, key="SELF", name="本人")
    permission = Permission.objects.create(
        app=app,
        key="customer.read",
        name="查看客户",
        supported_scopes=["SELF"],
    )
    group = AuthorizationGroup.objects.create(
        app=app,
        key="reader",
        kind="role",
        name="只读",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key="SELF",
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=[approver.authentik_user_id],
    )

    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        AccessRequestService.submit_grant_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                authorization_groups=(group,),
                direct_grants=(
                    ScopedAccessRequestGrant(permission=permission, scope_key="SELF"),
                ),
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=None,
                reason="重复目标必须拒绝",
                actor_type="user",
                actor_id=user.authentik_user_id,
                idempotency_key="reject-overlapping-target",
                approver_user_ids=(approver.authentik_user_id,),
            ),
        )

    assert "must not duplicate an active authorization group grant" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_managed_users_requires_resolved_direct_manager_as_approver() -> None:
    manager = UserMirror.objects.create(
        authentik_user_id="managed-manager",
        dingtalk_userid="managed-manager-dingtalk",
    )
    owner = UserMirror.objects.create(authentik_user_id="managed-owner")
    user = UserMirror.objects.create(
        authentik_user_id="managed-user",
        manager_userid=manager.dingtalk_userid,
    )
    app = App.objects.create(app_key="managed-approver-app", name="直属主管校验")
    _ = AppScope.objects.create(app=app, key="MANAGED_USERS", name="下级用户")
    permission = Permission.objects.create(
        app=app,
        key="customer.read",
        name="查看客户",
        supported_scopes=["MANAGED_USERS"],
    )

    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        AccessRequestService.submit_grant_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                direct_grants=(
                    ScopedAccessRequestGrant(
                        permission=permission,
                        scope_key="MANAGED_USERS",
                    ),
                ),
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=None,
                reason="App owner 不能替代直属主管",
                actor_type="user",
                actor_id=user.authentik_user_id,
                idempotency_key="reject-non-manager-approver",
                approver_user_ids=(owner.authentik_user_id,),
            ),
        )

    assert exc_info.value.messages == (
        "MANAGED_USERS requests require a direct manager approver.",
    )
    assert AccessRequest.objects.count() == 0
    assert AuditLog.objects.count() == 0

    access_request = AccessRequestService.submit_grant_request(
        AccessRequestSubmission(
            user=user,
            app=app,
            direct_grants=(
                ScopedAccessRequestGrant(
                    permission=permission,
                    scope_key="MANAGED_USERS",
                ),
            ),
            grant_type=GRANT_TYPE_PERMANENT,
            grant_expires_at=None,
            reason="由直属主管审批",
            actor_type="user",
            actor_id=user.authentik_user_id,
            idempotency_key="accept-direct-manager-approver",
            approver_user_ids=(manager.authentik_user_id,),
        ),
    )

    assert access_request.approver_assignments.get().approver == manager
