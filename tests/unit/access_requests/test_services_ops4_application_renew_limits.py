from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_TYPE_RENEW,
    AccessRequest,
    AccessRequestRole,
)
from easyauth.access_requests.services import (
    AccessRequestApplication,
    AccessRequestApplicationError,
    AccessRequestService,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, ApprovalRule, Role, RoleAccessPolicy
from easyauth.audit.models import AuditLog
from easyauth.grants.models import GRANT_STATUS_ACTIVE, AccessGrant, AccessGrantRole

pytestmark = pytest.mark.django_db

INITIAL_VERSION: Final = 1


def test_ops4_apply_approved_renew_request_rechecks_high_risk_duration_policy() -> None:
    # Given: 续期申请审批通过后, 高风险角色策略在应用前被收紧。
    user = UserMirror.objects.create(authentik_user_id="ops4-apply-renew-high-risk-user")
    app = App.objects.create(
        app_key="ops4-apply-renew-high-risk-app",
        name="OPS4 Apply Renew High Risk",
    )
    role = Role.objects.create(app=app, key="admin", name="Admin")
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])
    current_expires_at = timezone.now() + timedelta(days=3)
    requested_expires_at = timezone.now() + timedelta(days=10)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=current_expires_at,
    )
    _ = AccessGrantRole.objects.create(grant=grant, role=role)
    access_request = _approved_request(
        user=user,
        app=app,
        request_type=REQUEST_TYPE_RENEW,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=requested_expires_at,
    )
    _ = AccessRequestRole.objects.create(access_request=access_request, role=role)
    _ = RoleAccessPolicy.objects.create(
        role=role,
        is_high_risk=True,
        max_grant_duration_days=5,
    )

    # When / Then: 应用阶段重新按最新策略拒绝, 当前授权事实保持不变。
    with pytest.raises(AccessRequestApplicationError) as exc_info:
        _ = AccessRequestService.apply_approved_access_request(
            AccessRequestApplication(
                request_id=access_request.id,
                actor_type="approval",
                actor_id="dingtalk-callback",
            ),
        )

    grant.refresh_from_db()
    access_request.refresh_from_db()
    assert "grant apply failed" in str(exc_info.value)
    assert access_request.status == REQUEST_STATUS_GRANT_FAILED
    assert access_request.applied_at is None
    assert grant.status == GRANT_STATUS_ACTIVE
    assert grant.version == INITIAL_VERSION
    assert grant.grant_expires_at == current_expires_at
    assert AuditLog.objects.filter(event_type="grant_apply_failed").count() == 1


def _approved_request(
    *,
    user: UserMirror,
    app: App,
    request_type: str,
    grant_type: str = GRANT_TYPE_PERMANENT,
    grant_expires_at: datetime | None = None,
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
