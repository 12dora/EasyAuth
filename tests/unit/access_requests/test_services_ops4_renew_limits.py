from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    GRANT_TYPE_TIMED,
    REQUEST_STATUS_SUBMITTED,
    REQUEST_TYPE_RENEW,
    AccessRequest,
)
from easyauth.access_requests.services import (
    AccessRequestService,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AuthorizationGroup, AuthorizationGroupAccessPolicy
from easyauth.audit.models import AuditLog
from easyauth.grants.models import GRANT_TYPE_TIMED as GRANT_RECORD_TYPE_TIMED
from easyauth.grants.models import AccessGrant, AccessGrantGroup

pytestmark = pytest.mark.django_db


def test_ops4_submit_renew_request_rejects_high_risk_group_beyond_max_duration() -> None:
    # Given: 员工当前限时授权包含高风险授权组, 策略最多只允许 7 天。
    user = UserMirror.objects.create(authentik_user_id="ops4-renew-high-risk-user")
    app = App.objects.create(app_key="ops4-renew-high-risk-app", name="OPS4 Renew High Risk")
    authorization_group = AuthorizationGroup.objects.create(
        app=app,
        key="admin",
        kind="role",
        name="Admin",
    )
    _ = AuthorizationGroupAccessPolicy.objects.create(
        authorization_group=authorization_group,
        is_high_risk=True,
        max_grant_duration_days=7,
    )
    now = timezone.now()
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_RECORD_TYPE_TIMED,
        grant_expires_at=now + timedelta(days=3),
    )
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=authorization_group)

    # When / Then: 续期目标超过策略上限时被拒绝, 不写入申请或审计。
    with pytest.raises(AccessRequestSubmissionError) as exc_info:
        _ = AccessRequestService.submit_access_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                authorization_groups=(authorization_group,),
                grant_type=GRANT_TYPE_TIMED,
                grant_expires_at=now + timedelta(days=10),
                reason="高风险权限项目延期过长",
                actor_type="user",
                actor_id=user.authentik_user_id,
                request_type=REQUEST_TYPE_RENEW,
            ),
        )

    grant.refresh_from_db()
    assert "high-risk authorization group max duration" in str(exc_info.value)
    assert AccessRequest.objects.count() == 0
    assert AuditLog.objects.count() == 0
    assert grant.grant_expires_at == now + timedelta(days=3)


def test_ops4_submit_renew_request_accepts_high_risk_group_within_max_duration() -> None:
    # Given: 员工当前限时授权包含高风险授权组, 续期目标仍在策略上限内。
    user = UserMirror.objects.create(authentik_user_id="ops4-renew-high-risk-ok-user")
    app = App.objects.create(app_key="ops4-renew-high-risk-ok-app", name="OPS4 Renew Risk OK")
    authorization_group = AuthorizationGroup.objects.create(
        app=app,
        key="admin",
        kind="role",
        name="Admin",
    )
    _ = AuthorizationGroupAccessPolicy.objects.create(
        authorization_group=authorization_group,
        is_high_risk=True,
        max_grant_duration_days=14,
    )
    now = timezone.now()
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_RECORD_TYPE_TIMED,
        grant_expires_at=now + timedelta(days=3),
    )
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=authorization_group)

    # When: 员工提交未超过高风险策略上限的续期申请。
    access_request = AccessRequestService.submit_access_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                authorization_groups=(authorization_group,),
            grant_type=GRANT_TYPE_TIMED,
            grant_expires_at=now + timedelta(days=10),
            reason="高风险权限项目延期",
            actor_type="user",
            actor_id=user.authentik_user_id,
            request_type=REQUEST_TYPE_RENEW,
        ),
    )

    # Then: 申请进入 submitted, 当前授权等待审批后再改变。
    grant.refresh_from_db()
    assert access_request.request_type == REQUEST_TYPE_RENEW
    assert access_request.status == REQUEST_STATUS_SUBMITTED
    assert access_request.grant_expires_at == now + timedelta(days=10)
    assert grant.grant_expires_at == now + timedelta(days=3)
