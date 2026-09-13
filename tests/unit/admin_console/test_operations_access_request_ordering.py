from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Protocol, cast

import pytest
from django.test import Client
from django.utils import timezone

from easyauth.access_requests.models import (
    DECISION_ACTOR_CONSOLE_ADMIN,
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_STATUS_REJECTED,
    REQUEST_STATUS_SUBMITTED,
    REQUEST_TYPE_CHANGE,
    REQUEST_TYPE_GRANT,
    REQUEST_TYPE_REVOKE,
    AccessRequest,
    AccessRequestApprover,
)
from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog
from easyauth.grants.models import AccessGrant
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    install_authentik_authority,
    reset_authentik_authority,
)

if TYPE_CHECKING:
    from datetime import datetime

    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.django_db

REQUESTS_URL: Final = "/console/api/v1/operations/access-requests"


class _JsonResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, JsonValue]: ...


@pytest.fixture(autouse=True)
def _console_auth(monkeypatch: pytest.MonkeyPatch, settings: SettingsWrapper) -> None:
    settings.EASYAUTH_CONSOLE_SUPERUSER_GROUPS = ("easyauth-admins",)
    reset_authentik_authority()
    install_authentik_authority(monkeypatch)


def test_operations_access_requests_order_by_id_user_app_status_type_and_submitted_at() -> None:
    client = _admin("ord-ops-req-basic-admin")
    now = timezone.now()
    ada = UserMirror.objects.create(authentik_user_id="ord-ops-req-ada", name="Ada")
    cara = UserMirror.objects.create(authentik_user_id="ord-ops-req-cara", name="Cara")
    ben = UserMirror.objects.create(authentik_user_id="ord-ops-req-ben", name="Ben")
    app_a = App.objects.create(app_key="ord-ops-req-a", name="A")
    app_m = App.objects.create(app_key="ord-ops-req-m", name="M")
    app_z = App.objects.create(app_key="ord-ops-req-z", name="Z")
    grant_a = AccessGrant.objects.create(user=ada, app=app_a)
    grant_z = AccessGrant.objects.create(user=cara, app=app_z)
    first = _request(
        ada,
        app_z,
        key="ord-ops-req-1",
        request_type=REQUEST_TYPE_REVOKE,
        status=REQUEST_STATUS_SUBMITTED,
        submitted_at=now - timedelta(hours=2),
        base_grant=grant_a,
    )
    second = _request(
        ben,
        app_m,
        key="ord-ops-req-2",
        request_type=REQUEST_TYPE_GRANT,
        status=REQUEST_STATUS_REJECTED,
        submitted_at=now - timedelta(hours=1),
    )
    third = _request(
        cara,
        app_a,
        key="ord-ops-req-3",
        request_type=REQUEST_TYPE_CHANGE,
        status=REQUEST_STATUS_GRANT_APPLIED,
        submitted_at=now,
        base_grant=grant_z,
    )

    assert _ids(client, "id") == [first.id, second.id, third.id]
    assert _ids(client, "-id") == [third.id, second.id, first.id]
    assert _ids(client, "user") == [first.id, second.id, third.id]
    assert _ids(client, "-user") == [third.id, second.id, first.id]
    assert _ids(client, "app_key") == [third.id, second.id, first.id]
    assert _ids(client, "-app_key") == [first.id, second.id, third.id]
    assert _ids(client, "status") == [third.id, second.id, first.id]
    assert _ids(client, "-status") == [first.id, second.id, third.id]
    assert _ids(client, "request_type") == [third.id, second.id, first.id]
    assert _ids(client, "-request_type") == [first.id, second.id, third.id]
    assert _ids(client, "submitted_at") == [first.id, second.id, third.id]
    assert _ids(client, "-submitted_at") == [third.id, second.id, first.id]


def test_operations_access_requests_approver_coalesce_and_nulls_last() -> None:
    client = _admin("ord-ops-req-approver-admin")
    user = UserMirror.objects.create(authentik_user_id="ord-ops-req-approver-user")
    app = App.objects.create(app_key="ord-ops-req-approver-app", name="A")
    ada = UserMirror.objects.create(authentik_user_id="ord-ops-req-appr-ada", name="Ada")
    cara = UserMirror.objects.create(authentik_user_id="ord-ops-req-appr-cara", name="Cara")
    ben = UserMirror.objects.create(authentik_user_id="ord-ops-req-appr-ben", name="Ben")
    pending_ada = _request(user, app, key="ord-ops-req-appr-1")
    _ = AccessRequestApprover.objects.create(access_request=pending_ada, approver=ada)
    pending_cara = _request(user, app, key="ord-ops-req-appr-2")
    _ = AccessRequestApprover.objects.create(access_request=pending_cara, approver=cara)
    decided = _request(
        user,
        app,
        key="ord-ops-req-appr-3",
        status=REQUEST_STATUS_REJECTED,
        decided_by=ben.authentik_user_id,
    )
    missing = _request(user, app, key="ord-ops-req-appr-4")

    assert _ids(client, "approvers") == [
        pending_ada.id,
        decided.id,
        pending_cara.id,
        missing.id,
    ]
    assert _ids(client, "-approvers") == [
        pending_cara.id,
        decided.id,
        pending_ada.id,
        missing.id,
    ]


def test_operations_access_requests_order_by_failure_reason_groups_failed_rows() -> None:
    client = _admin("ord-ops-req-fail-admin")
    user = UserMirror.objects.create(authentik_user_id="ord-ops-req-fail-user")
    app = App.objects.create(app_key="ord-ops-req-fail-app", name="A")
    ok_a = _request(user, app, key="ord-ops-req-fail-ok-a")
    failed = _request(
        user,
        app,
        key="ord-ops-req-fail-hit",
        status=REQUEST_STATUS_GRANT_FAILED,
        decided_by="ord-ops-req-fail-admin",
        actor_type=DECISION_ACTOR_CONSOLE_ADMIN,
    )
    ok_b = _request(user, app, key="ord-ops-req-fail-ok-b")
    _ = AuditLog.objects.create(
        actor_type="admin",
        actor_id="ord-ops-req-fail-admin",
        event_type="grant_apply_failed",
        target_type="access_request",
        target_id=str(failed.id),
        metadata={"error": "目录写入失败"},
    )

    assert _ids(client, "failure_reason") == [ok_a.id, ok_b.id, failed.id]
    assert _ids(client, "-failure_reason") == [failed.id, ok_a.id, ok_b.id]


def test_operations_access_requests_reject_unknown_ordering() -> None:
    client = _admin("ord-ops-req-unknown-admin")
    response = client.get(REQUESTS_URL, {"ordering": "does_not_exist"})
    _assert_unknown(response, "does_not_exist")


def _request(  # noqa: PLR0913 - 运营申请夹具按排序字段铺开。
    user: UserMirror,
    app: App,
    *,
    key: str,
    request_type: str = REQUEST_TYPE_GRANT,
    status: str = REQUEST_STATUS_SUBMITTED,
    submitted_at: datetime | None = None,
    base_grant: AccessGrant | None = None,
    decided_by: str = "",
    actor_type: str = DECISION_ACTOR_CONSOLE_ADMIN,
) -> AccessRequest:
    now = timezone.now()
    kwargs: dict[str, object] = {
        "user": user,
        "app": app,
        "reason": key,
        "idempotency_key": key,
        "payload_digest": key.encode().hex()[:64].ljust(64, "0"),
        "request_type": request_type,
        "status": status,
    }
    if base_grant is not None:
        kwargs["base_grant"] = base_grant
        kwargs["base_grant_revision"] = base_grant.version
    if status != REQUEST_STATUS_SUBMITTED:
        kwargs["decided_by"] = decided_by or "ord-ops-decider"
        kwargs["decision_actor_type"] = actor_type
        kwargs["decided_at"] = now
        if status == REQUEST_STATUS_REJECTED:
            kwargs["decision_comment"] = "驳回"
        elif status == REQUEST_STATUS_GRANT_APPLIED:
            kwargs["approved_at"] = now
            kwargs["applied_at"] = now
        else:
            kwargs["approved_at"] = now
    access_request = AccessRequest.objects.create(**kwargs)  # type: ignore[arg-type]
    if submitted_at is not None:
        _ = AccessRequest.objects.filter(pk=access_request.pk).update(submitted_at=submitted_at)
        access_request.refresh_from_db()
    return access_request


def _admin(username: str) -> Client:
    return authenticate_console_admin(Client(HTTP_HOST="localhost"), username)


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
