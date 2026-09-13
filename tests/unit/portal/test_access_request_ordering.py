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
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_REJECTED,
    AccessRequest,
    AccessRequestApprover,
    AccessRequestGroup,
)
from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App, AuthorizationGroup
from tests.integration.portal.helpers import logged_in_client

if TYPE_CHECKING:
    from datetime import datetime

    from django.test import Client

pytestmark = pytest.mark.django_db

REQUESTS_URL: Final = "/portal/api/v1/me/access-requests"


class _JsonResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, JsonValue]: ...


def test_portal_access_requests_order_by_app_key_reason_and_created_at() -> None:
    client, user = logged_in_client("portal-req-order-basic")
    now = timezone.now()
    app_z = App.objects.create(app_key="portal-req-z", name="Z")
    app_m = App.objects.create(app_key="portal-req-m", name="M")
    app_a = App.objects.create(app_key="portal-req-a", name="A")
    oldest = _request(
        user,
        app_z,
        "zzz-reason",
        "portal-req-old",
        submitted_at=now - timedelta(hours=2),
    )
    middle = _request(
        user,
        app_m,
        "mmm-reason",
        "portal-req-mid",
        submitted_at=now - timedelta(hours=1),
    )
    newest = _request(user, app_a, "aaa-reason", "portal-req-new", submitted_at=now)

    assert _ids(client, "app_key") == [newest.id, middle.id, oldest.id]
    assert _ids(client, "-app_key") == [oldest.id, middle.id, newest.id]
    assert _ids(client, "reason") == [newest.id, middle.id, oldest.id]
    assert _ids(client, "-reason") == [oldest.id, middle.id, newest.id]
    assert _ids(client, "created_at") == [oldest.id, middle.id, newest.id]
    assert _ids(client, "-created_at") == [newest.id, middle.id, oldest.id]


def test_portal_access_requests_order_by_status() -> None:
    client, user = logged_in_client("portal-req-order-status")
    app = App.objects.create(app_key="portal-req-status-app", name="Status")
    submitted = _request(user, app, "s", "portal-req-status-s")
    rejected = _rejected(
        user,
        app,
        "r",
        "portal-req-status-r",
        decided_by="portal-req-order-status",
    )
    applied = _rejected(
        user,
        app,
        "g",
        "portal-req-status-g",
        decided_by="portal-req-order-status",
        status=REQUEST_STATUS_GRANT_APPLIED,
    )

    assert _ids(client, "status") == [applied.id, rejected.id, submitted.id]
    assert _ids(client, "-status") == [submitted.id, rejected.id, applied.id]


def test_portal_access_requests_order_by_groups_places_empty_last() -> None:
    client, user = logged_in_client("portal-req-order-groups")
    app = App.objects.create(app_key="portal-req-groups-app", name="Groups")
    alpha = _request(user, app, "a", "portal-req-groups-a", group_name="Alpha")
    zeta = _request(user, app, "z", "portal-req-groups-z", group_name="Zeta")
    empty = _request(user, app, "n", "portal-req-groups-n")

    assert _ids(client, "groups") == [alpha.id, zeta.id, empty.id]
    assert _ids(client, "-groups") == [zeta.id, alpha.id, empty.id]


def test_portal_access_requests_order_by_expires_at_places_permanent_last() -> None:
    client, user = logged_in_client("portal-req-order-term")
    app = App.objects.create(app_key="portal-req-term-app", name="Term")
    soon = _request(
        user,
        app,
        "soon",
        "portal-req-term-soon",
        grant_type=GRANT_TYPE_TIMED,
        expires_in_days=2,
    )
    later = _request(
        user,
        app,
        "later",
        "portal-req-term-later",
        grant_type=GRANT_TYPE_TIMED,
        expires_in_days=10,
    )
    permanent = _request(user, app, "perm", "portal-req-term-perm")

    assert _ids(client, "expires_at") == [soon.id, later.id, permanent.id]
    assert _ids(client, "-expires_at") == [later.id, soon.id, permanent.id]


def test_portal_access_requests_approver_coalesce_and_nulls_last() -> None:
    client, user = logged_in_client("portal-req-order-approver")
    app = App.objects.create(app_key="portal-req-approver-app", name="Approver")
    ada = UserMirror.objects.create(authentik_user_id="portal-req-approver-ada", name="Ada")
    cara = UserMirror.objects.create(authentik_user_id="portal-req-approver-cara", name="Cara")
    ben = UserMirror.objects.create(authentik_user_id="portal-req-approver-ben", name="Ben")
    pending_ada = _request(user, app, "ada", "portal-req-approver-pending-ada")
    _ = AccessRequestApprover.objects.create(access_request=pending_ada, approver=ada)
    pending_cara = _request(user, app, "cara", "portal-req-approver-pending-cara")
    _ = AccessRequestApprover.objects.create(access_request=pending_cara, approver=cara)
    decided = _rejected(
        user,
        app,
        "ben",
        "portal-req-approver-decided",
        decided_by=ben.authentik_user_id,
    )
    missing = _request(user, app, "none", "portal-req-approver-missing")

    assert _ids(client, "approver") == [pending_ada.id, decided.id, pending_cara.id, missing.id]
    assert _ids(client, "-approver") == [pending_cara.id, decided.id, pending_ada.id, missing.id]


def test_portal_access_requests_reject_unknown_ordering() -> None:
    client, _user = logged_in_client("portal-req-order-unknown")
    response = client.get(REQUESTS_URL, {"ordering": "does_not_exist"})
    _assert_unknown(response, "does_not_exist")


def _request(  # noqa: PLR0913 - 测试夹具按申请排序字段铺开。
    user: UserMirror,
    app: App,
    reason: str,
    idempotency_key: str,
    *,
    grant_type: str = GRANT_TYPE_PERMANENT,
    expires_in_days: int | None = None,
    group_name: str | None = None,
    submitted_at: datetime | None = None,
) -> AccessRequest:
    expires_at = (
        timezone.now() + timedelta(days=expires_in_days) if expires_in_days is not None else None
    )
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        reason=reason,
        idempotency_key=idempotency_key,
        payload_digest=_digest(idempotency_key),
        grant_type=grant_type,
        grant_expires_at=expires_at,
    )
    if group_name is not None:
        group = AuthorizationGroup.objects.create(
            app=app,
            key=idempotency_key,
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


def _rejected(  # noqa: PLR0913 - 测试夹具按申请决定字段铺开。
    user: UserMirror,
    app: App,
    reason: str,
    idempotency_key: str,
    *,
    decided_by: str,
    status: str = REQUEST_STATUS_REJECTED,
) -> AccessRequest:
    now = timezone.now()
    if status == REQUEST_STATUS_REJECTED:
        return AccessRequest.objects.create(
            user=user,
            app=app,
            reason=reason,
            idempotency_key=idempotency_key,
            payload_digest=_digest(idempotency_key),
            status=status,
            decided_by=decided_by,
            decision_actor_type=DECISION_ACTOR_USER,
            decided_at=now,
            decision_comment="驳回",
        )
    return AccessRequest.objects.create(
        user=user,
        app=app,
        reason=reason,
        idempotency_key=idempotency_key,
        payload_digest=_digest(idempotency_key),
        status=status,
        decided_by=decided_by,
        decision_actor_type=DECISION_ACTOR_USER,
        decided_at=now,
        approved_at=now,
        applied_at=now,
    )


def _ids(client: Client, ordering: str) -> list[int]:
    response = client.get(REQUESTS_URL, {"ordering": ordering, "page_size": "20"})
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
