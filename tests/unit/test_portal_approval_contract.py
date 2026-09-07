from __future__ import annotations

import pytest

from easyauth.access_requests.models import AccessRequest
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.portal.approvals_api import _approval_item


@pytest.mark.django_db
def test_portal_approval_row_exact_keys() -> None:
    user = UserMirror.objects.create(authentik_user_id="contract-applicant")
    app = App.objects.create(app_key="contract-app", name="契约测试应用")
    row = AccessRequest.objects.create(
        user=user,
        app=app,
        reason="契约测试",
        idempotency_key="contract-request",
        payload_digest="a" * 64,
    )
    # 与 frontend/src/pages/portal/components/portalApprovalPayload.ts 的
    # APPROVAL_ROW_KEYS 保持同步, 两份字段列表必须同时修改。
    assert set(_approval_item(row)) == {
        "id",
        "app_key",
        "app_name",
        "app_alias",
        "request_type",
        "base_grant_id",
        "base_grant_revision",
        "status",
        "status_label",
        "grant_type",
        "grant_expires_at",
        "reason",
        "submitted_at",
        "authorization_groups",
        "direct_grants",
        "current_approvers",
        "decided_by",
        "decision_actor_type",
        "decided_by_name",
        "decided_at",
        "decision_comment",
        "approved_at",
        "applied_at",
        "withdrawn_at",
        "applicant",
        "approver_user_ids",
    }
