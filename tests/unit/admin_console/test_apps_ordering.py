from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Protocol, cast

import pytest
from django.test import Client

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import (
    App,
    AppMembership,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.applications.services import AppCredentialService
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    install_authentik_authority,
    reset_authentik_authority,
)

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.django_db

APPS_URL: Final = "/console/api/v1/apps"


class _JsonResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, JsonValue]: ...


@pytest.fixture(autouse=True)
def _console_auth(monkeypatch: pytest.MonkeyPatch, settings: SettingsWrapper) -> None:
    settings.EASYAUTH_CONSOLE_SUPERUSER_GROUPS = ("easyauth-admins",)
    reset_authentik_authority()
    install_authentik_authority(monkeypatch)


def test_console_apps_order_by_owners_places_missing_last() -> None:
    client = _admin("ord-apps-owners-admin")
    ada = UserMirror.objects.create(authentik_user_id="ord-apps-owner-ada", name="Ada")
    cara = UserMirror.objects.create(authentik_user_id="ord-apps-owner-cara", name="Cara")
    ada_app = _app("ord-apps-ada")
    cara_app = _app("ord-apps-cara")
    empty_app = _app("ord-apps-none")
    _ = AppMembership.objects.create(app=ada_app, user_id=ada.authentik_user_id, role="owner")
    _ = AppMembership.objects.create(app=cara_app, user_id=cara.authentik_user_id, role="owner")
    zed = UserMirror.objects.create(authentik_user_id="ord-apps-owner-zed", name="Zed")
    _ = AppMembership.objects.create(app=cara_app, user_id=zed.authentik_user_id, role="owner")

    assert _keys(client, "owners") == [ada_app.app_key, cara_app.app_key, empty_app.app_key]
    assert _keys(client, "-owners") == [cara_app.app_key, ada_app.app_key, empty_app.app_key]


def test_console_apps_order_by_configuration_status_then_paginate() -> None:
    client = _admin("ord-apps-status-admin")
    blocking = _app("ord-apps-blocking")
    warning = _warning_app("ord-apps-warning")
    ready = _ready_app("ord-apps-ready")

    ascending = _page(client, "configuration_status", page=1, page_size=2)
    ascending_rest = _page(client, "configuration_status", page=2, page_size=2)
    descending = _page(client, "-configuration_status", page=1, page_size=2)
    descending_rest = _page(client, "-configuration_status", page=2, page_size=2)

    assert [item["app_key"] for item in ascending] == [blocking.app_key, warning.app_key]
    assert [item["configuration_status"] for item in ascending] == ["blocking", "warning"]
    assert [item["app_key"] for item in ascending_rest] == [ready.app_key]
    assert [item["configuration_status"] for item in ascending_rest] == ["ready"]
    assert [item["app_key"] for item in descending] == [ready.app_key, warning.app_key]
    assert [item["configuration_status"] for item in descending] == ["ready", "warning"]
    assert [item["app_key"] for item in descending_rest] == [blocking.app_key]
    assert [item["configuration_status"] for item in descending_rest] == ["blocking"]


def test_console_apps_reject_unknown_ordering() -> None:
    client = _admin("ord-apps-unknown-admin")
    response = client.get(APPS_URL, {"ordering": "not-a-column"})
    _assert_unknown(response, "not-a-column")


def _app(app_key: str) -> App:
    return App.objects.create(app_key=app_key, name=app_key)


def _warning_app(app_key: str) -> App:
    app = _app(app_key)
    owner = UserMirror.objects.create(authentik_user_id=f"{app_key}-owner", name="Warn")
    _ = AppMembership.objects.create(app=app, user_id=owner.authentik_user_id, role="owner")
    _ = AuthorizationGroup.objects.create(
        app=app,
        key="role",
        kind="role",
        name="Role",
        requestable=False,
    )
    _ = Permission.objects.create(app=app, key="warn.perm", name="Warn", supported_scopes=[])
    _ = AppCredentialService.create_static_token(app=app, name=f"{app_key}-token")
    return app


def _ready_app(app_key: str) -> App:
    app = _app(app_key)
    owner = UserMirror.objects.create(authentik_user_id=f"{app_key}-owner", name="Ready")
    _ = AppMembership.objects.create(app=app, user_id=owner.authentik_user_id, role="owner")
    scope = AppScope.objects.create(app=app, key="GLOBAL", name="Global")
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Read",
        supported_scopes=[scope.key],
    )
    group = AuthorizationGroup.objects.create(
        app=app,
        key="auditor",
        kind="role",
        name="Auditor",
        requestable=True,
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key=scope.key,
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )
    _ = AppCredentialService.create_static_token(app=app, name=f"{app_key}-token")
    return app


def _admin(username: str) -> Client:
    return authenticate_console_admin(Client(HTTP_HOST="localhost"), username)


def _keys(client: Client, ordering: str) -> list[str]:
    return [str(item["app_key"]) for item in _page(client, ordering, page=1, page_size=20)]


def _page(
    client: Client,
    ordering: str,
    *,
    page: int,
    page_size: int,
) -> list[dict[str, JsonValue]]:
    response = client.get(
        APPS_URL,
        {"ordering": ordering, "page": str(page), "page_size": str(page_size)},
    )
    assert response.status_code == HTTPStatus.OK, response.content
    payload = cast("dict[str, JsonValue]", response.json())
    data = payload["data"]
    assert isinstance(data, list), payload
    items: list[dict[str, JsonValue]] = []
    for item in data:
        assert isinstance(item, dict), payload
        items.append(item)
    return items


def _assert_unknown(response: _JsonResponse, value: str) -> None:
    assert response.status_code == HTTPStatus.BAD_REQUEST
    payload = cast("dict[str, JsonValue]", response.json())
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert error["details"] == {"field": "ordering", "value": value}
