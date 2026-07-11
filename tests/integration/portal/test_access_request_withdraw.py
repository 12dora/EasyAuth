from __future__ import annotations

from http import HTTPStatus
from typing import Final

import pytest

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_SUBMITTED,
    REQUEST_STATUS_WITHDRAWN,
    AccessRequest,
    AccessRequestApprover,
)
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog
from tests.integration.portal.helpers import logged_in_client

pytestmark = pytest.mark.django_db

WITHDRAW_URL: Final = "/portal/api/v1/me/access-requests/{request_id}/withdraw"


def test_requester_can_withdraw_submitted_request_idempotently() -> None:
    # Given: 申请人有一笔 submitted 申请。
    client, user = logged_in_client("portal-withdraw-owner")
    app = App.objects.create(app_key="portal-withdraw-app", name="Withdraw App")
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        status=REQUEST_STATUS_SUBMITTED,
        grant_type=GRANT_TYPE_PERMANENT,
        reason="临时需要",
        idempotency_key="withdraw-idem-1",
        payload_digest="a" * 64,
    )
    url = WITHDRAW_URL.format(request_id=access_request.id)

    # When: 连续撤回两次。
    first = client.post(url, data="{}", content_type="application/json")
    second = client.post(url, data="{}", content_type="application/json")

    # Then: 均 200, 状态为 withdrawn; 审计只记一次。
    access_request.refresh_from_db()
    assert first.status_code == HTTPStatus.OK
    assert second.status_code == HTTPStatus.OK
    assert first.json()["access_request"]["status"] == REQUEST_STATUS_WITHDRAWN
    assert second.json()["access_request"]["status"] == REQUEST_STATUS_WITHDRAWN
    assert first.json()["access_request"]["status_label"] == "已撤回"
    assert access_request.status == REQUEST_STATUS_WITHDRAWN
    assert AuditLog.objects.filter(event_type="access_request_withdrawn").count() == 1


def test_withdraw_rejects_non_owner_and_terminal_status() -> None:
    # Given: 他人申请 + 本人已审批申请。
    owner_client, owner = logged_in_client("portal-withdraw-real-owner")
    other_client, other = logged_in_client("portal-withdraw-other")
    app = App.objects.create(app_key="portal-withdraw-scope", name="Scope App")
    owned = AccessRequest.objects.create(
        user=owner,
        app=app,
        status=REQUEST_STATUS_SUBMITTED,
        grant_type=GRANT_TYPE_PERMANENT,
        reason="owner",
        idempotency_key="withdraw-owned",
        payload_digest="b" * 64,
    )
    decided = AccessRequest.objects.create(
        user=other,
        app=app,
        status=REQUEST_STATUS_APPROVED,
        grant_type=GRANT_TYPE_PERMANENT,
        reason="already decided",
        idempotency_key="withdraw-decided",
        payload_digest="c" * 64,
    )
    approver = UserMirror.objects.create(
        authentik_user_id="portal-withdraw-approver",
        status=USER_STATUS_ACTIVE,
    )
    _ = AccessRequestApprover.objects.create(access_request=owned, approver=approver)

    # When
    cross = other_client.post(
        WITHDRAW_URL.format(request_id=owned.id),
        data="{}",
        content_type="application/json",
    )
    conflict = other_client.post(
        WITHDRAW_URL.format(request_id=decided.id),
        data="{}",
        content_type="application/json",
    )
    missing = owner_client.post(
        WITHDRAW_URL.format(request_id=999_999),
        data="{}",
        content_type="application/json",
    )
    unauthenticated = owner_client.__class__().post(
        WITHDRAW_URL.format(request_id=owned.id),
        data="{}",
        content_type="application/json",
    )

    # Then
    owned.refresh_from_db()
    assert cross.status_code == HTTPStatus.NOT_FOUND
    assert owned.status == REQUEST_STATUS_SUBMITTED
    assert conflict.status_code == HTTPStatus.CONFLICT
    assert missing.status_code == HTTPStatus.NOT_FOUND
    assert unauthenticated.status_code == HTTPStatus.UNAUTHORIZED
