from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Protocol, cast

import pytest
from django.test import Client

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.teams.models import TEAM_MEMBER_ROLE_LEADER, TEAM_MEMBER_ROLE_MEMBER, Team, TeamMember
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    install_authentik_authority,
    reset_authentik_authority,
)

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.django_db

TEAMS_URL: Final = "/console/api/v1/teams"


class _JsonResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, JsonValue]: ...


@pytest.fixture(autouse=True)
def _console_auth(monkeypatch: pytest.MonkeyPatch, settings: SettingsWrapper) -> None:
    settings.EASYAUTH_CONSOLE_SUPERUSER_GROUPS = ("easyauth-admins",)
    reset_authentik_authority()
    install_authentik_authority(monkeypatch)


def test_console_teams_order_by_leaders_places_missing_last() -> None:
    client = _admin("ord-teams-leaders-admin")
    ada = UserMirror.objects.create(authentik_user_id="ord-teams-ada", name="Ada")
    cara = UserMirror.objects.create(authentik_user_id="ord-teams-cara", name="Cara")
    ada_team = Team.objects.create(name="Ord Team Ada")
    cara_team = Team.objects.create(name="Ord Team Cara")
    empty_team = Team.objects.create(name="Ord Team Empty")
    _ = TeamMember.objects.create(team=ada_team, user=ada, role=TEAM_MEMBER_ROLE_LEADER)
    _ = TeamMember.objects.create(team=cara_team, user=cara, role=TEAM_MEMBER_ROLE_LEADER)
    _ = TeamMember.objects.create(team=empty_team, user=ada, role=TEAM_MEMBER_ROLE_MEMBER)

    assert _names(client, "leaders") == [ada_team.name, cara_team.name, empty_team.name]
    assert _names(client, "-leaders") == [cara_team.name, ada_team.name, empty_team.name]


def test_console_teams_order_by_name_and_status() -> None:
    client = _admin("ord-teams-name-admin")
    active_z = Team.objects.create(name="Ord Zulu", is_active=True)
    inactive_a = Team.objects.create(name="Ord Alpha", is_active=False)
    active_m = Team.objects.create(name="Ord Mu", is_active=True)

    assert _names(client, "name") == [inactive_a.name, active_m.name, active_z.name]
    assert _names(client, "-name") == [active_z.name, active_m.name, inactive_a.name]
    assert _names(client, "status") == [inactive_a.name, active_z.name, active_m.name]
    assert _names(client, "-status") == [active_z.name, active_m.name, inactive_a.name]


def test_console_teams_reject_unknown_ordering() -> None:
    client = _admin("ord-teams-unknown-admin")
    response = client.get(TEAMS_URL, {"ordering": "nope"})
    _assert_unknown(response, "nope")


def _admin(username: str) -> Client:
    return authenticate_console_admin(Client(HTTP_HOST="localhost"), username)


def _names(client: Client, ordering: str) -> list[str]:
    response = client.get(TEAMS_URL, {"ordering": ordering, "page_size": "20"})
    assert response.status_code == HTTPStatus.OK, response.content
    payload = cast("dict[str, JsonValue]", response.json())
    data = payload["data"]
    assert isinstance(data, list), payload
    names: list[str] = []
    for item in data:
        assert isinstance(item, dict), payload
        names.append(str(item["name"]))
    return names


def _assert_unknown(response: _JsonResponse, value: str) -> None:
    assert response.status_code == HTTPStatus.BAD_REQUEST
    payload = cast("dict[str, JsonValue]", response.json())
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert error["details"] == {"field": "ordering", "value": value}
