from __future__ import annotations

import pytest

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    REQUEST_STATUS_SUBMITTED,
    REQUEST_TYPE_GRANT,
    AccessRequest,
)
from easyauth.access_requests.services import (
    AccessRequestService,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, ApprovalRule, AuthorizationGroup
from easyauth.grants.models import AccessGrant

pytestmark = pytest.mark.django_db


def _group_with_rule(app: App) -> AuthorizationGroup:
    group = AuthorizationGroup.objects.create(app=app, key="admin", kind="role", name="Admin")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )
    return group


def test_submit_grant_request_allows_permanent_for_any_group() -> None:
    # Given: 一个可申请授权组(高风险时长机制已移除, 任何权限都可申请永久)。
    user = UserMirror.objects.create(authentik_user_id="permanent-grant-user")
    approver = UserMirror.objects.create(authentik_user_id="permanent-grant-approver")
    app = App.objects.create(app_key="permanent-grant-app", name="Permanent Grant")
    group = _group_with_rule(app)

    # When: 员工申请永久授权。
    access_request = AccessRequestService.submit_access_request(
        AccessRequestSubmission(
            user=user,
            app=app,
            authorization_groups=(group,),
            grant_type=GRANT_TYPE_PERMANENT,
            grant_expires_at=None,
            reason="申请永久授权",
            actor_type="user",
            actor_id=user.authentik_user_id,
            idempotency_key="permanent-grant-success",
            approver_user_ids=(approver.authentik_user_id,),
            request_type=REQUEST_TYPE_GRANT,
        ),
    )

    # Then: 提交成功, 不再被高风险时长限制拒绝。
    assert access_request.status == REQUEST_STATUS_SUBMITTED
    assert access_request.grant_type == GRANT_TYPE_PERMANENT


def test_submit_grant_request_rejects_when_current_grant_exists() -> None:
    # Given: 员工已持有该 App 的 current 授权。
    user = UserMirror.objects.create(authentik_user_id="dup-grant-user")
    app = App.objects.create(app_key="dup-grant-app", name="Dup Grant")
    group = AuthorizationGroup.objects.create(app=app, key="viewer", kind="role", name="Viewer")
    _ = AccessGrant.objects.create(user=user, app=app)

    # When / Then: grant 请求在提交阶段 fail-fast, 不再等审批落地时撞唯一约束。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_access_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                authorization_groups=(group,),
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=None,
                reason="重复申请",
                actor_type="user",
                actor_id=user.authentik_user_id,
                idempotency_key="permanent-grant-current-exists",
                request_type=REQUEST_TYPE_GRANT,
            ),
        )

    assert "current grant already exists" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0
