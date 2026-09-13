from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Protocol, cast

import pytest
from django.test import Client

from easyauth.accounts.models import USER_STATUS_ACTIVE, USER_STATUS_DEPARTED, UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    install_authentik_authority,
    reset_authentik_authority,
)

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.django_db

USERS_URL: Final = "/console/api/v1/users"


class _JsonResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, JsonValue]: ...


@pytest.fixture(autouse=True)
def _console_auth(monkeypatch: pytest.MonkeyPatch, settings: SettingsWrapper) -> None:
    settings.EASYAUTH_CONSOLE_SUPERUSER_GROUPS = ("easyauth-admins",)
    reset_authentik_authority()
    install_authentik_authority(monkeypatch)


def test_console_people_order_by_is_console_admin() -> None:
    client = _admin("people-sort-admin")
    ada = UserMirror.objects.create(
        authentik_user_id="people-sort-ada",
        name="PeopleSort Ada",
        is_console_admin=False,
    )
    ben = UserMirror.objects.create(
        authentik_user_id="people-sort-ben",
        name="PeopleSort Ben",
        is_console_admin=True,
    )
    cara = UserMirror.objects.create(
        authentik_user_id="people-sort-cara",
        name="PeopleSort Cara",
        is_console_admin=False,
    )

    assert _ids(client, "is_console_admin") == [
        ada.authentik_user_id,
        cara.authentik_user_id,
        ben.authentik_user_id,
    ]
    assert _ids(client, "-is_console_admin") == [
        ben.authentik_user_id,
        ada.authentik_user_id,
        cara.authentik_user_id,
    ]


def test_console_people_order_by_name_department_email_status() -> None:
    client = _admin("people-sort-fields-admin")
    ada = UserMirror.objects.create(
        authentik_user_id="people-fields-ada",
        name="PeopleFields Ada",
        department="Alpha",
        email="ada@example.com",
        status=USER_STATUS_ACTIVE,
    )
    cara = UserMirror.objects.create(
        authentik_user_id="people-fields-cara",
        name="PeopleFields Cara",
        department="Zulu",
        email="cara@example.com",
        status=USER_STATUS_DEPARTED,
    )
    ben = UserMirror.objects.create(
        authentik_user_id="people-fields-ben",
        name="PeopleFields Ben",
        department="Mu",
        email="ben@example.com",
        status=USER_STATUS_ACTIVE,
    )

    assert _ids(client, "name", query="PeopleFields") == [
        ada.authentik_user_id,
        ben.authentik_user_id,
        cara.authentik_user_id,
    ]
    assert _ids(client, "department", query="PeopleFields") == [
        ada.authentik_user_id,
        ben.authentik_user_id,
        cara.authentik_user_id,
    ]
    assert _ids(client, "email", query="PeopleFields") == [
        ada.authentik_user_id,
        ben.authentik_user_id,
        cara.authentik_user_id,
    ]
    assert _ids(client, "status", query="PeopleFields") == [
        ada.authentik_user_id,
        ben.authentik_user_id,
        cara.authentik_user_id,
    ]
    assert _ids(client, "-status", query="PeopleFields") == [
        cara.authentik_user_id,
        ada.authentik_user_id,
        ben.authentik_user_id,
    ]


def test_console_people_reject_unknown_ordering() -> None:
    client = _admin("people-sort-unknown-admin")
    response = client.get(USERS_URL, {"ordering": "unknown"})
    _assert_unknown(response, "unknown")


def _admin(username: str) -> Client:
    return authenticate_console_admin(Client(HTTP_HOST="localhost"), username)


def _ids(client: Client, ordering: str, *, query: str = "PeopleSort") -> list[str]:
    response = client.get(
        USERS_URL,
        {"ordering": ordering, "q": query, "page_size": "20"},
    )
    assert response.status_code == HTTPStatus.OK, response.content
    payload = cast("dict[str, JsonValue]", response.json())
    data = payload["data"]
    assert isinstance(data, list), payload
    user_ids: list[str] = []
    for item in data:
        assert isinstance(item, dict), payload
        user_ids.append(str(item["user_id"]))
    return user_ids


def _assert_unknown(response: _JsonResponse, value: str) -> None:
    assert response.status_code == HTTPStatus.BAD_REQUEST
    payload = cast("dict[str, JsonValue]", response.json())
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert error["details"] == {"field": "ordering", "value": value}
