from __future__ import annotations

from datetime import timedelta
from typing import Final

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    REQUEST_STATUS_SUBMITTED,
    AccessRequest,
    AccessRequestRole,
)
from easyauth.access_requests.services import (
    AccessRequestService,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, ApprovalRule, Role
from easyauth.audit.models import AuditLog
from easyauth.grants.models import AccessGrant

pytestmark = pytest.mark.django_db

EXPECTED_AUDIT_COUNT: Final = 1


def test_s14_submit_grant_request_creates_submitted_request_without_creating_grant() -> None:
    # Given: 一个员工选择了有审批规则的可申请角色。
    user = UserMirror.objects.create(authentik_user_id="s14-service-user")
    app = App.objects.create(app_key="s14-service-crm", name="S14 CRM")
    role = Role.objects.create(app=app, key="admin", name="CRM 管理员", requestable=True)
    _ = ApprovalRule.objects.create(
        app=app,
        role=role,
        approver_userids=["manager-001"],
    )

    # When: 员工提交授权申请。
    access_request = AccessRequestService.submit_grant_request(
        AccessRequestSubmission(
            user=user,
            app=app,
            roles=(role,),
            grant_type=GRANT_TYPE_PERMANENT,
            grant_expires_at=None,
            reason="需要处理客户资料",
            actor_type="user",
            actor_id=user.authentik_user_id,
        ),
    )

    # Then: 服务只创建 submitted 申请和审计, 不直接创建授权记录。
    assert access_request.status == REQUEST_STATUS_SUBMITTED
    assert AccessRequestRole.objects.get(access_request=access_request).role == role
    assert access_request.reason == "需要处理客户资料"
    assert AccessGrant.objects.count() == 0
    audit_log = AuditLog.objects.get(event_type="access_request_submitted")
    assert audit_log.actor_type == "user"
    assert audit_log.actor_id == user.authentik_user_id
    assert audit_log.target_type == "access_request"
    assert audit_log.metadata["app_key"] == app.app_key
    assert audit_log.metadata["roles"] == [role.key]


def test_s14_submit_grant_request_rejects_role_without_active_approval_rule() -> None:
    # Given: 一个角色可申请但没有有效审批规则。
    user = UserMirror.objects.create(authentik_user_id="s14-service-no-rule-user")
    app = App.objects.create(app_key="s14-service-no-rule-app", name="S14 No Rule")
    role = Role.objects.create(app=app, key="auditor", name="CRM 审计员", requestable=True)

    # When / Then: 服务拒绝提交, 不落库申请、授权或审计。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_grant_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                roles=(role,),
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=None,
                reason="需要审计客户资料",
                actor_type="user",
                actor_id=user.authentik_user_id,
            ),
        )

    assert "approval rule" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0
    assert AccessGrant.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_s14_submit_grant_request_rejects_role_from_another_app() -> None:
    # Given: 一个员工选择了其他应用的角色。
    user = UserMirror.objects.create(authentik_user_id="s14-service-cross-app-user")
    app = App.objects.create(app_key="s14-service-cross-app", name="S14 Cross App")
    other_app = App.objects.create(app_key="s14-service-other-app", name="S14 Other App")
    role = Role.objects.create(app=other_app, key="admin", name="Other 管理员")
    _ = ApprovalRule.objects.create(
        app=other_app,
        role=role,
        approver_userids=["manager-001"],
    )

    # When / Then: 服务拒绝提交, 不落库申请。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_grant_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                roles=(role,),
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=None,
                reason="跨应用角色不应提交",
                actor_type="user",
                actor_id=user.authentik_user_id,
            ),
        )

    assert "Role must belong" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0


def test_s14_submit_grant_request_rejects_non_requestable_role() -> None:
    # Given: 一个角色有审批规则但被标记为不可申请。
    user = UserMirror.objects.create(authentik_user_id="s14-service-not-requestable-user")
    app = App.objects.create(app_key="s14-service-not-requestable", name="S14 Not Requestable")
    role = Role.objects.create(
        app=app,
        key="admin",
        name="CRM 管理员",
        requestable=False,
    )
    _ = ApprovalRule.objects.create(
        app=app,
        role=role,
        approver_userids=["manager-001"],
    )

    # When / Then: 服务拒绝提交, 不落库申请。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_grant_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                roles=(role,),
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=None,
                reason="不可申请角色不应提交",
                actor_type="user",
                actor_id=user.authentik_user_id,
            ),
        )

    assert "requestable" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0


def test_s14_submit_grant_request_rejects_inactive_role() -> None:
    # Given: 一个角色有审批规则但已停用。
    user = UserMirror.objects.create(authentik_user_id="s14-service-inactive-role-user")
    app = App.objects.create(app_key="s14-service-inactive-role", name="S14 Inactive Role")
    role = Role.objects.create(app=app, key="admin", name="CRM 管理员", is_active=False)
    _ = ApprovalRule.objects.create(
        app=app,
        role=role,
        approver_userids=["manager-001"],
    )

    # When / Then: 服务拒绝提交, 不落库申请。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_grant_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                roles=(role,),
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=None,
                reason="停用角色不应提交",
                actor_type="user",
                actor_id=user.authentik_user_id,
            ),
        )

    assert "active" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0


def test_s14_submit_permanent_grant_request_rejects_expiration() -> None:
    # Given: 一个员工选择永久授权但提供了过期时间。
    user = UserMirror.objects.create(authentik_user_id="s14-service-permanent-exp-user")
    app = App.objects.create(app_key="s14-service-permanent-exp", name="S14 Permanent Exp")
    role = Role.objects.create(app=app, key="admin", name="CRM 管理员")
    _ = ApprovalRule.objects.create(
        app=app,
        role=role,
        approver_userids=["manager-001"],
    )

    # When / Then: 服务拒绝提交, 不落库申请。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_grant_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                roles=(role,),
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=timezone.now(),
                reason="永久授权不应带过期时间",
                actor_type="user",
                actor_id=user.authentik_user_id,
            ),
        )

    assert "Permanent" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0


def test_s14_submit_timed_grant_request_requires_expiration() -> None:
    # Given: 一个员工选择限时授权但没有提供过期时间。
    user = UserMirror.objects.create(authentik_user_id="s14-service-timed-no-exp-user")
    app = App.objects.create(app_key="s14-service-timed-no-exp", name="S14 Timed No Exp")
    role = Role.objects.create(app=app, key="admin", name="CRM 管理员")
    _ = ApprovalRule.objects.create(
        app=app,
        role=role,
        approver_userids=["manager-001"],
    )

    # When / Then: 服务拒绝提交, 不落库申请。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_grant_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                roles=(role,),
                grant_type=GRANT_TYPE_TIMED,
                grant_expires_at=None,
                reason="限时授权必须带过期时间",
                actor_type="user",
                actor_id=user.authentik_user_id,
            ),
        )

    assert "Timed" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0


def test_s14_submit_timed_grant_request_preserves_requested_expiration() -> None:
    # Given: 一个员工选择了限时授权。
    user = UserMirror.objects.create(authentik_user_id="s14-service-timed-user")
    app = App.objects.create(app_key="s14-service-timed-app", name="S14 Timed")
    role = Role.objects.create(app=app, key="operator", name="CRM 操作员", requestable=True)
    _ = ApprovalRule.objects.create(
        app=app,
        role=role,
        approver_userids=["manager-001"],
    )
    grant_expires_at = timezone.now() + timedelta(days=7)

    # When: 员工提交限时申请。
    access_request = AccessRequestService.submit_grant_request(
        AccessRequestSubmission(
            user=user,
            app=app,
            roles=(role,),
            grant_type=GRANT_TYPE_TIMED,
            grant_expires_at=grant_expires_at,
            reason="临时处理活动客户",
            actor_type="user",
            actor_id=user.authentik_user_id,
        ),
    )

    # Then: 申请保留限时生命周期和到期时间。
    assert access_request.grant_type == GRANT_TYPE_TIMED
    assert access_request.grant_expires_at == grant_expires_at
    assert AuditLog.objects.count() == EXPECTED_AUDIT_COUNT
