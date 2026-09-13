from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Protocol, cast

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    DECISION_ACTOR_USER,
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_REJECTED,
    REQUEST_TYPE_CHANGE,
    REQUEST_TYPE_GRANT,
    REQUEST_TYPE_REVOKE,
    AccessRequest,
    AccessRequestApprover,
    AccessRequestGroup,
)
from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App, AuthorizationGroup
from easyauth.grants.models import AccessGrant
from tests.integration.portal.helpers import logged_in_client

if TYPE_CHECKING:
    from datetime import datetime

    from django.test import Client

pytestmark = pytest.mark.django_db

APPROVALS_URL: Final = "/portal/api/v1/me/approvals"


class _JsonResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, JsonValue]: ...


def test_portal_pending_approvals_order_by_app_applicant_content_term_reason() -> None:
    client, approver = logged_in_client("portal-appr-pending")
    now = timezone.now()
    ada = UserMirror.objects.create(authentik_user_id="portal-appr-ada", name="Ada")
    cara = UserMirror.objects.create(authentik_user_id="portal-appr-cara", name="Cara")
    ben = UserMirror.objects.create(authentik_user_id="portal-appr-ben", name="Ben")
    app_a = App.objects.create(app_key="portal-appr-a", name="A")
    app_m = App.objects.create(app_key="portal-appr-m", name="M")
    app_z = App.objects.create(app_key="portal-appr-z", name="Z")
    ada_req = _pending(
        ada,
        app_z,
        approver,
        reason="zzz",
        key="portal-appr-ada-req",
        group_name="Zeta",
        submitted_at=now - timedelta(hours=2),
        grant_type=GRANT_TYPE_TIMED,
        expires_in_days=2,
    )
    ben_req = _pending(
        ben,
        app_m,
        approver,
        reason="mmm",
        key="portal-appr-ben-req",
        group_name="Mu",
        submitted_at=now - timedelta(hours=1),
        grant_type=GRANT_TYPE_TIMED,
        expires_in_days=8,
    )
    cara_req = _pending(
        cara,
        app_a,
        approver,
        reason="aaa",
        key="portal-appr-cara-req",
        submitted_at=now,
    )

    assert _ids(client, "app_key") == [cara_req.id, ben_req.id, ada_req.id]
    assert _ids(client, "-app_key") == [ada_req.id, ben_req.id, cara_req.id]
    assert _ids(client, "applicant") == [ada_req.id, ben_req.id, cara_req.id]
    assert _ids(client, "-applicant") == [cara_req.id, ben_req.id, ada_req.id]
    assert _ids(client, "content") == [ben_req.id, ada_req.id, cara_req.id]
    assert _ids(client, "-content") == [ada_req.id, ben_req.id, cara_req.id]
    assert _ids(client, "term") == [ada_req.id, ben_req.id, cara_req.id]
    assert _ids(client, "-term") == [ben_req.id, ada_req.id, cara_req.id]
    assert _ids(client, "reason") == [cara_req.id, ben_req.id, ada_req.id]
    assert _ids(client, "-reason") == [ada_req.id, ben_req.id, cara_req.id]
    assert _ids(client, "created_at") == [ada_req.id, ben_req.id, cara_req.id]
    assert _ids(client, "-created_at") == [cara_req.id, ben_req.id, ada_req.id]


def test_portal_pending_approvals_order_by_request_type() -> None:
    client, approver = logged_in_client("portal-appr-type")
    ada = UserMirror.objects.create(authentik_user_id="portal-appr-type-ada", name="Ada")
    ben = UserMirror.objects.create(authentik_user_id="portal-appr-type-ben", name="Ben")
    cara = UserMirror.objects.create(authentik_user_id="portal-appr-type-cara", name="Cara")
    app = App.objects.create(app_key="portal-appr-type-app", name="Type")
    grant_ada = AccessGrant.objects.create(user=ada, app=app)
    grant_cara = AccessGrant.objects.create(user=cara, app=app)
    revoke_req = _pending(
        ada,
        app,
        approver,
        reason="revoke",
        key="portal-appr-type-revoke",
        request_type=REQUEST_TYPE_REVOKE,
        base_grant=grant_ada,
    )
    grant_req = _pending(
        ben,
        app,
        approver,
        reason="grant",
        key="portal-appr-type-grant",
        request_type=REQUEST_TYPE_GRANT,
    )
    change_req = _pending(
        cara,
        app,
        approver,
        reason="change",
        key="portal-appr-type-change",
        request_type=REQUEST_TYPE_CHANGE,
        base_grant=grant_cara,
    )

    assert _ids(client, "request_type") == [change_req.id, grant_req.id, revoke_req.id]
    assert _ids(client, "-request_type") == [revoke_req.id, grant_req.id, change_req.id]


def test_portal_processed_approvals_order_by_status_comment_and_decided_at() -> None:
    client, actor = logged_in_client("portal-appr-processed")
    now = timezone.now()
    applicant = UserMirror.objects.create(authentik_user_id="portal-appr-processed-user")
    app = App.objects.create(app_key="portal-appr-processed-app", name="Processed")
    approved = _processed(
        applicant,
        app,
        actor.authentik_user_id,
        status=REQUEST_STATUS_APPROVED,
        key="portal-appr-processed-approved",
        comment="",
        decided_at=now - timedelta(hours=2),
    )
    applied = _processed(
        applicant,
        app,
        actor.authentik_user_id,
        status=REQUEST_STATUS_GRANT_APPLIED,
        key="portal-appr-processed-applied",
        comment="mmm",
        decided_at=now - timedelta(hours=1),
    )
    rejected = _processed(
        applicant,
        app,
        actor.authentik_user_id,
        status=REQUEST_STATUS_REJECTED,
        key="portal-appr-processed-rejected",
        comment="zzz",
        decided_at=now,
    )

    assert _ids(client, "status", status="processed") == [approved.id, applied.id, rejected.id]
    assert _ids(client, "-status", status="processed") == [rejected.id, applied.id, approved.id]
    assert _ids(client, "decision_comment", status="processed") == [
        applied.id,
        rejected.id,
        approved.id,
    ]
    assert _ids(client, "-decision_comment", status="processed") == [
        rejected.id,
        applied.id,
        approved.id,
    ]
    assert _ids(client, "decided_at", status="processed") == [approved.id, applied.id, rejected.id]
    assert _ids(client, "-decided_at", status="processed") == [rejected.id, applied.id, approved.id]


def test_portal_approvals_reject_unknown_ordering() -> None:
    client, _user = logged_in_client("portal-appr-unknown")
    response = client.get(APPROVALS_URL, {"ordering": "nope"})
    _assert_unknown(response, "nope")


def _pending(  # noqa: PLR0913 - 测试夹具按待审批排序字段铺开。
    applicant: UserMirror,
    app: App,
    approver: UserMirror,
    *,
    reason: str,
    key: str,
    group_name: str | None = None,
    submitted_at: datetime | None = None,
    grant_type: str = GRANT_TYPE_PERMANENT,
    expires_in_days: int | None = None,
    request_type: str = REQUEST_TYPE_GRANT,
    base_grant: AccessGrant | None = None,
) -> AccessRequest:
    expires_at = (
        timezone.now() + timedelta(days=expires_in_days) if expires_in_days is not None else None
    )
    access_request = AccessRequest.objects.create(
        user=applicant,
        app=app,
        reason=reason,
        idempotency_key=key,
        payload_digest=_digest(key),
        grant_type=grant_type,
        grant_expires_at=expires_at,
        request_type=request_type,
        base_grant=base_grant,
        base_grant_revision=None if base_grant is None else base_grant.version,
    )
    _ = AccessRequestApprover.objects.create(access_request=access_request, approver=approver)
    if group_name is not None:
        group = AuthorizationGroup.objects.create(
            app=app,
            key=key,
            kind="role",
            name=group_name,
            requestable=False,
        )
        _ = AccessRequestGroup.objects.create(
            access_request=access_request,
            authorization_group=group,
        )
    if submitted_at is not None:
        _ = AccessRequest.objects.filter(pk=access_request.pk).update(submitted_at=submitted_at)
        access_request.refresh_from_db()
    return access_request


def _processed(  # noqa: PLR0913 - 测试夹具按已处理审批字段铺开。
    applicant: UserMirror,
    app: App,
    actor_id: str,
    *,
    status: str,
    key: str,
    comment: str,
    decided_at: datetime,
) -> AccessRequest:
    approved_at = None if status == REQUEST_STATUS_REJECTED else decided_at
    applied_at = decided_at if status == REQUEST_STATUS_GRANT_APPLIED else None
    access_request = AccessRequest.objects.create(
        user=applicant,
        app=app,
        reason="processed",
        idempotency_key=key,
        payload_digest=_digest(key),
        status=status,
        decided_by=actor_id,
        decision_actor_type=DECISION_ACTOR_USER,
        decided_at=decided_at,
        decision_comment=comment,
        approved_at=approved_at,
        applied_at=applied_at,
    )
    _ = AccessRequest.objects.filter(pk=access_request.pk).update(decided_at=decided_at)
    access_request.refresh_from_db()
    return access_request


def _ids(client: Client, ordering: str, *, status: str = "pending") -> list[int]:
    response = client.get(
        APPROVALS_URL,
        {"ordering": ordering, "status": status, "page_size": "20"},
    )
    assert response.status_code == HTTPStatus.OK, response.content
    payload = cast("dict[str, JsonValue]", response.json())
    data = payload["data"]
    assert isinstance(data, list), payload
    ids: list[int] = []
    for item in data:
        assert isinstance(item, dict), payload
        request_id = item["id"]
        assert isinstance(request_id, int)
        ids.append(request_id)
    return ids


def _assert_unknown(response: _JsonResponse, value: str) -> None:
    assert response.status_code == HTTPStatus.BAD_REQUEST
    payload = cast("dict[str, JsonValue]", response.json())
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert error["details"] == {"field": "ordering", "value": value}


def _digest(seed: str) -> str:
    return seed.encode().hex()[:64].ljust(64, "0")
