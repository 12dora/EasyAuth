from __future__ import annotations

from http import HTTPStatus

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


@pytest.fixture(autouse=True)
def _clear_health_cache() -> None:  # pyright: ignore[reportUnusedFunction]
    cache.clear()


@pytest.mark.django_db
def test_strict_health_requires_background_heartbeats(
    monkeypatch: pytest.MonkeyPatch,
    settings: object,
) -> None:
    monkeypatch.setattr(urls, "_database_ready", lambda: True)
    monkeypatch.setattr(urls, "_broker_ready", lambda: True)
    monkeypatch.setattr(settings, "EASYAUTH_HEALTH_REQUIRE_BACKGROUND", True)

    response = Client().get("/health/")

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

    response = Client().get("/health/")

    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"]["database"]["healthy"] is True
    assert payload["checks"]["broker"]["healthy"] is True
