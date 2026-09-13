from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Protocol, cast

import pytest
from django.test import Client
from django.utils import timezone

from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App, PermissionTemplateVersion
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    install_authentik_authority,
    reset_authentik_authority,
)

if TYPE_CHECKING:
    from datetime import datetime

    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.django_db


class _JsonResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, JsonValue]: ...


@pytest.fixture(autouse=True)
def _console_auth(monkeypatch: pytest.MonkeyPatch, settings: SettingsWrapper) -> None:
    settings.EASYAUTH_CONSOLE_SUPERUSER_GROUPS = ("easyauth-admins",)
    reset_authentik_authority()
    install_authentik_authority(monkeypatch)


def test_template_versions_order_by_imported_by_and_imported_at() -> None:
    client = _admin("ord-tmpl-admin")
    app = App.objects.create(app_key="ord-tmpl-app", name="Template")
    now = timezone.now()
    ada = _version(app, version=1, imported_by="ada", imported_at=now - timedelta(days=2))
    cara = _version(app, version=3, imported_by="cara", imported_at=now)
    ben = _version(app, version=2, imported_by="ben", imported_at=now - timedelta(days=1))
    url = f"/console/api/v1/apps/{app.app_key}/permission-template-versions"

    assert _versions(client, url, "imported_by") == [ada.version, ben.version, cara.version]
    assert _versions(client, url, "-imported_by") == [cara.version, ben.version, ada.version]
    assert _versions(client, url, "imported_at") == [ada.version, ben.version, cara.version]
    assert _versions(client, url, "-imported_at") == [cara.version, ben.version, ada.version]
    assert _versions(client, url, "version") == [ada.version, ben.version, cara.version]
    items = _items(client, url, "imported_at")
    assert all("imported_at" in item and "imported_by" in item for item in items)


def test_template_versions_reject_unknown_ordering() -> None:
    client = _admin("ord-tmpl-unknown-admin")
    app = App.objects.create(app_key="ord-tmpl-unknown", name="Template")
    response = client.get(
        f"/console/api/v1/apps/{app.app_key}/permission-template-versions",
        {"ordering": "unknown"},
    )
    _assert_unknown(response, "unknown")


def _version(
    app: App,
    *,
    version: int,
    imported_by: str,
    imported_at: datetime,
) -> PermissionTemplateVersion:
    return PermissionTemplateVersion.objects.create(
        app=app,
        version=version,
        source="manual",
        content_hash=str(version) * 64,
        imported_by=imported_by,
        imported_at=imported_at,
    )


def _admin(username: str) -> Client:
    return authenticate_console_admin(Client(HTTP_HOST="localhost"), username)


def _versions(client: Client, url: str, ordering: str) -> list[int]:
    return [int(item["version"]) for item in _items(client, url, ordering)]


def _items(client: Client, url: str, ordering: str) -> list[dict[str, JsonValue]]:
    response = client.get(url, {"ordering": ordering, "page_size": "20"})
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
