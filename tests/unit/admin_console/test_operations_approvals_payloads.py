from __future__ import annotations

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    DECISION_ACTOR_CONSOLE_ADMIN,
    GRANT_TYPE_PERMANENT,
    REQUEST_STATUS_APPROVED,
    AccessRequest,
    AccessRequestApprover,
)
from easyauth.accounts.models import UserMirror
from easyauth.admin_console.operations_approvals_api import _request_item
from easyauth.admin_console.operations_payloads import access_request_decision_fields
from easyauth.applications.models import App

pytestmark = pytest.mark.django_db


def test_request_item_reuses_access_request_decision_fields() -> None:
    user = UserMirror.objects.create(authentik_user_id="ops-approval-user")
    approver = UserMirror.objects.create(authentik_user_id="ops-approval-approver")
    app = App.objects.create(app_key="ops-approval-app", name="CRM")
    decided_at = timezone.now()
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        status=REQUEST_STATUS_APPROVED,
        grant_type=GRANT_TYPE_PERMANENT,
        reason="代审",
        idempotency_key="ops-approval-key",
        payload_digest="d" * 64,
        approved_at=decided_at,
        decided_at=decided_at,
        decided_by="ops-approval-admin",
        decision_actor_type=DECISION_ACTOR_CONSOLE_ADMIN,
        decision_comment="审批人休假",
    )
    _ = AccessRequestApprover.objects.create(access_request=access_request, approver=approver)

    item = _request_item(access_request)

    assert item["id"] == access_request.id
    assert item["user_id"] == user.authentik_user_id
    assert item["app_key"] == app.app_key
    assert item["status"] == REQUEST_STATUS_APPROVED
    for key, value in access_request_decision_fields(access_request).items():
        assert item[key] == value
    assert item["approver_user_ids"] == [approver.authentik_user_id]
    assert item["decided_by"] == "ops-approval-admin"
    assert item["decision_actor_type"] == DECISION_ACTOR_CONSOLE_ADMIN
    assert item["decision_comment"] == "审批人休假"
