from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, cast

import pytest
from django.core.cache import cache
from django.test import Client

from easyauth.config import urls
from easyauth.config.runtime_health import (
    BEAT_WORKER_HEARTBEAT,
    DIRECTORY_SYNC_SUCCESS,
    GRANT_CLEANUP_SUCCESS,
    STREAM_PROCESS_HEARTBEAT,
    mark_heartbeat,
)

if TYPE_CHECKING:
    from django.http import HttpRequest


@pytest.fixture(autouse=True)
def _clear_health_cache() -> None:  # pyright: ignore[reportUnusedFunction]
    cache.clear()


def _admin_actor(_request: HttpRequest) -> str:
    return "admin"


@pytest.mark.django_db
def test_strict_health_requires_background_heartbeats(
    monkeypatch: pytest.MonkeyPatch,
    settings: object,
) -> None:
    monkeypatch.setattr(urls, "_database_ready", lambda: True)
    monkeypatch.setattr(urls, "_broker_ready", lambda: True)
    monkeypatch.setattr(settings, "EASYAUTH_HEALTH_REQUIRE_BACKGROUND", True)

    monkeypatch.setattr(urls, "require_superuser", _admin_actor)

    response = Client().get("/health/readiness/")

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.json()["checks"][BEAT_WORKER_HEARTBEAT]["healthy"] is False


@pytest.mark.django_db
def test_strict_health_reports_real_runtime_components(
    monkeypatch: pytest.MonkeyPatch,
    settings: object,
) -> None:
    monkeypatch.setattr(urls, "_database_ready", lambda: True)
    monkeypatch.setattr(urls, "_broker_ready", lambda: True)
    monkeypatch.setattr(settings, "EASYAUTH_HEALTH_REQUIRE_BACKGROUND", True)
    for heartbeat in (
        BEAT_WORKER_HEARTBEAT,
        STREAM_PROCESS_HEARTBEAT,
        GRANT_CLEANUP_SUCCESS,
        DIRECTORY_SYNC_SUCCESS,
    ):
        mark_heartbeat(heartbeat)

    monkeypatch.setattr(urls, "require_superuser", _admin_actor)

    response = Client().get("/health/readiness/")

    assert response.status_code == HTTPStatus.OK
    payload = cast("dict[str, object]", response.json())
    assert payload["status"] == "ok"
    checks = cast("dict[str, object]", payload["checks"])
    database = cast("dict[str, object]", checks["database"])
    broker = cast("dict[str, object]", checks["broker"])
    assert database["healthy"] is True
    assert broker["healthy"] is True


@pytest.mark.django_db
def test_anonymous_health_only_reports_fixed_liveness() -> None:
    response = Client().get("/health/")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_readiness_requires_authorized_admin() -> None:
    response = Client().get("/health/readiness/")

    assert response.status_code == HTTPStatus.UNAUTHORIZED
