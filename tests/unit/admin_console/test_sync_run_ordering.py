from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Protocol, cast

import pytest
from django.test import Client
from django.utils import timezone

from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App
from easyauth.connectors.models import ConnectorInstance, ConnectorSyncRun
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    install_authentik_authority,
    reset_authentik_authority,
)

if TYPE_CHECKING:
    from datetime import datetime

    from pytest_django.fixtures import SettingsWrapper

    from easyauth.applications.ops_models import JsonValue as ConnectorJson

pytestmark = pytest.mark.django_db


class _JsonResponse(Protocol):
    status_code: int

    def json(self) -> dict[str, JsonValue]: ...


@pytest.fixture(autouse=True)
def _console_auth(monkeypatch: pytest.MonkeyPatch, settings: SettingsWrapper) -> None:
    settings.EASYAUTH_CONSOLE_SUPERUSER_GROUPS = ("easyauth-admins",)
    reset_authentik_authority()
    install_authentik_authority(monkeypatch)


def test_sync_runs_order_by_error_stats_status_and_trigger() -> None:
    app = App.objects.create(app_key="ord-sync-app", name="Sync")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    client = _admin("ord-sync-admin")
    now = timezone.now()
    alpha = _run(
        instance,
        trigger="manual",
        status="success",
        started_at=now - timedelta(hours=2),
        error="alpha",
        stats={"api_calls": 1},
    )
    zeta = _run(
        instance,
        trigger="periodic",
        status="partial",
        started_at=now - timedelta(hours=1),
        error="zeta",
        stats={"api_calls": 10},
    )
    empty = _run(
        instance,
        trigger="event",
        status="failed",
        started_at=now,
        error="",
        stats={},
    )
    url = f"/console/api/v1/apps/{app.app_key}/connectors/{instance.id}/sync-runs"

    assert _ids(client, url, "error") == [alpha.id, zeta.id, empty.id]
    assert _ids(client, url, "-error") == [zeta.id, alpha.id, empty.id]
    assert _ids(client, url, "stats") == [alpha.id, zeta.id, empty.id]
    assert _ids(client, url, "-stats") == [zeta.id, alpha.id, empty.id]
    assert _ids(client, url, "status") == [empty.id, zeta.id, alpha.id]
    assert _ids(client, url, "trigger") == [empty.id, alpha.id, zeta.id]
    assert _ids(client, url, "started_at") == [alpha.id, zeta.id, empty.id]


def test_sync_runs_reject_unknown_ordering() -> None:
    app = App.objects.create(app_key="ord-sync-unknown", name="Sync")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    client = _admin("ord-sync-unknown-admin")
    response = client.get(
        f"/console/api/v1/apps/{app.app_key}/connectors/{instance.id}/sync-runs",
        {"ordering": "unknown"},
    )
    _assert_unknown(response, "unknown")


def _run(  # noqa: PLR0913 - 同步运行夹具按排序字段铺开。
    instance: ConnectorInstance,
    *,
    trigger: str,
    status: str,
    started_at: datetime,
    error: str,
    stats: dict[str, ConnectorJson],
) -> ConnectorSyncRun:
    return ConnectorSyncRun.objects.create(
        instance=instance,
        trigger=trigger,
        status=status,
        started_at=started_at,
        finished_at=started_at + timedelta(seconds=1),
        error=error,
        stats=stats,
    )


def _admin(username: str) -> Client:
    return authenticate_console_admin(Client(HTTP_HOST="localhost"), username)


def _ids(client: Client, url: str, ordering: str) -> list[int]:
    response = client.get(url, {"ordering": ordering, "page_size": "20"})
    assert response.status_code == HTTPStatus.OK, response.content
    payload = cast("dict[str, JsonValue]", response.json())
    data = payload["data"]
    assert isinstance(data, list), payload
    ids: list[int] = []
    for item in data:
        assert isinstance(item, dict), payload
        run_id = item["id"]
        assert isinstance(run_id, int)
        ids.append(run_id)
    return ids


def _assert_unknown(response: _JsonResponse, value: str) -> None:
    assert response.status_code == HTTPStatus.BAD_REQUEST
    payload = cast("dict[str, JsonValue]", response.json())
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert error["details"] == {"field": "ordering", "value": value}
