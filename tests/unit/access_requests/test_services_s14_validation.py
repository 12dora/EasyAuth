from __future__ import annotations

import pytest

from easyauth.access_requests.models import GRANT_TYPE_PERMANENT, AccessRequest, AccessRequestGroup
from easyauth.access_requests.services import (
    AccessRequestService,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, ApprovalRule, AuthorizationGroup
from easyauth.audit.models import AuditLog
from easyauth.grants.models import AccessGrant

pytestmark = pytest.mark.django_db


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
        ),
    )

    # Then: 只创建一条授权组链接, 审计授权组列表也去重。
    assert AccessRequestGroup.objects.filter(access_request=access_request).count() == 1
    audit_log = AuditLog.objects.get(event_type="access_request_submitted")
    assert audit_log.metadata["authorization_group_keys"] == [group.key]
