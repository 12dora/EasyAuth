from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    REQUEST_TYPE_CHANGE,
    REQUEST_TYPE_GRANT,
    AccessRequest,
)
from easyauth.access_requests.services import (
    AccessRequestService,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    ApprovalRule,
    AuthorizationGroup,
    AuthorizationGroupAccessPolicy,
)
from easyauth.grants.models import GRANT_TYPE_TIMED as GRANT_RECORD_TYPE_TIMED
from easyauth.grants.models import AccessGrant, AccessGrantGroup

pytestmark = pytest.mark.django_db


def _high_risk_group(app: App, *, max_days: int = 7) -> AuthorizationGroup:
    group = AuthorizationGroup.objects.create(app=app, key="admin", kind="role", name="Admin")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )
    _ = AuthorizationGroupAccessPolicy.objects.create(
        authorization_group=group,
        is_high_risk=True,
        max_grant_duration_days=max_days,
    )
    return group


def test_submit_grant_request_rejects_high_risk_group_beyond_max_duration() -> None:
    # Given: 高风险授权组策略最多 7 天, 员工直接申请 10 年期新授权。
    user = UserMirror.objects.create(authentik_user_id="high-risk-grant-user")
    app = App.objects.create(app_key="high-risk-grant-app", name="High Risk Grant")
    group = _high_risk_group(app)

    # When / Then: 提交阶段直接拒绝。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_access_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                authorization_groups=(group,),
                grant_type=GRANT_TYPE_TIMED,
                grant_expires_at=timezone.now() + timedelta(days=3650),
                reason="十年期高风险授权",
                actor_type="user",
                actor_id=user.authentik_user_id,
                request_type=REQUEST_TYPE_GRANT,
            ),
        )

    assert "high-risk authorization group max duration" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0


def test_submit_change_request_rejects_high_risk_group_permanent_conversion() -> None:
    # Given: 员工持有高风险组 7 天限时授权, 试图通过 change 转成永久授权。
    user = UserMirror.objects.create(authentik_user_id="high-risk-change-user")
    app = App.objects.create(app_key="high-risk-change-app", name="High Risk Change")
    group = _high_risk_group(app)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_RECORD_TYPE_TIMED,
        grant_expires_at=timezone.now() + timedelta(days=3),
    )
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=group)

    # When / Then: change 与 renew 同口径, 不允许绕过期限上限转永久。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_access_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                authorization_groups=(group,),
                grant_type=GRANT_TYPE_PERMANENT,
                grant_expires_at=None,
                reason="高风险授权转永久",
                actor_type="user",
                actor_id=user.authentik_user_id,
                request_type=REQUEST_TYPE_CHANGE,
            ),
        )

    assert "cannot be granted permanently" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0


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
                request_type=REQUEST_TYPE_GRANT,
            ),
        )

    assert "current grant already exists" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0
