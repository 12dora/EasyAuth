from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import TYPE_CHECKING

import pytest
from django.test import RequestFactory

from easyauth.admin_console import settings_api
from easyauth.applications.integration_settings import (
    DingTalkCredentialTriple,
    DingTalkRuntimeConfig,
    IntegrationSettings,
)

if TYPE_CHECKING:
    from django.http import HttpRequest

pytestmark = pytest.mark.django_db(transaction=True)


class _ConnectivityClient:
    def __init__(self) -> None:
        self.force_refresh_values: list[bool] = []

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        self.force_refresh_values.append(force_refresh)
        return "fresh-token"


def test_connectivity_check_forces_fresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _ConnectivityClient()

    def require_superuser(_request: HttpRequest) -> str:
        return "admin"

    def from_settings() -> _ConnectivityClient:
        return client

    def record_test(*, actor_id: str, ok: bool, error: str) -> None:
        del actor_id, ok, error

    monkeypatch.setattr(settings_api, "require_superuser", require_superuser)
    monkeypatch.setattr(
        settings_api.DingTalkApiClient,  # pyright: ignore[reportPrivateLocalImportUsage]
        "from_settings",
        from_settings,
    )
    monkeypatch.setattr(settings_api, "_record_dingtalk_test", record_test)

    response = settings_api.console_dingtalk_connectivity_test(RequestFactory().post("/"))

    assert response.status_code == HTTPStatus.OK
    assert client.force_refresh_values == [True]


def test_connectivity_check_probes_notify_triple_when_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = _ConnectivityClient()
    notify = _ConnectivityClient()
    config = DingTalkRuntimeConfig(
        app_key="main-key",
        app_secret="main-secret",
        agent_id="1001",
        timeout_seconds=5,
        notify=DingTalkCredentialTriple(
            app_key="svc-key",
            app_secret="svc-secret",
            agent_id="9001",
        ),
    )

    def require_superuser(_request: HttpRequest) -> str:
        return "admin"

    def record_test(*, actor_id: str, ok: bool, error: str) -> None:
        del actor_id, ok, error

    monkeypatch.setattr(settings_api, "require_superuser", require_superuser)
    monkeypatch.setattr(
        settings_api.DingTalkApiClient,  # pyright: ignore[reportPrivateLocalImportUsage]
        "from_settings",
        lambda: main,
    )
    monkeypatch.setattr(
        settings_api.DingTalkApiClient,  # pyright: ignore[reportPrivateLocalImportUsage]
        "from_notify_settings",
        lambda: notify,
    )
    monkeypatch.setattr(settings_api, "dingtalk_runtime_config", lambda: config)
    monkeypatch.setattr(settings_api, "_record_dingtalk_test", record_test)

    response = settings_api.console_dingtalk_connectivity_test(RequestFactory().post("/"))

    assert response.status_code == HTTPStatus.OK
    assert main.force_refresh_values == [True]
    assert notify.force_refresh_values == [True]


def test_credential_update_invalidates_previous_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _ = IntegrationSettings.objects.create(
        pk=1,
        dingtalk_app_key="old-app",
        dingtalk_app_secret="old-secret",
    )
    invalidated: list[tuple[str, str]] = []

    def invalidate(*, app_key: str, app_secret: str) -> None:
        invalidated.append((app_key, app_secret))

    monkeypatch.setattr(settings_api, "invalidate_access_token", invalidate)
    request = RequestFactory().patch(
        "/",
        data=dumps({"dingtalk_app_key": "new-app"}),
        content_type="application/json",
    )

    response = settings_api._update_settings(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        request,
        actor_id="admin",
    )

    assert response.status_code == HTTPStatus.OK
    assert invalidated == [("old-app", "old-secret")]


def test_notify_credential_update_invalidates_previous_notify_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = IntegrationSettings.objects.create(
        pk=1,
        dingtalk_app_key="main-app",
        dingtalk_app_secret="main-secret",
        dingtalk_notify_app_key="old-svc",
        dingtalk_notify_app_secret="old-svc-secret",
        dingtalk_notify_agent_id="9001",
    )
    invalidated: list[tuple[str, str]] = []

    def invalidate(*, app_key: str, app_secret: str) -> None:
        invalidated.append((app_key, app_secret))

    monkeypatch.setattr(settings_api, "invalidate_access_token", invalidate)
    request = RequestFactory().patch(
        "/",
        data=dumps({"dingtalk_notify_app_key": "new-svc"}),
        content_type="application/json",
    )

    response = settings_api._update_settings(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        request,
        actor_id="admin",
    )

    assert response.status_code == HTTPStatus.OK
    assert invalidated == [("old-svc", "old-svc-secret")]


def test_incomplete_notify_patch_does_not_invalidate_main_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = IntegrationSettings.objects.create(
        pk=1,
        dingtalk_app_key="main-app",
        dingtalk_app_secret="main-secret",
        dingtalk_agent_id="1001",
    )
    invalidated: list[tuple[str, str]] = []

    def invalidate(*, app_key: str, app_secret: str) -> None:
        invalidated.append((app_key, app_secret))

    monkeypatch.setattr(settings_api, "invalidate_access_token", invalidate)
    request = RequestFactory().patch(
        "/",
        data=dumps({"dingtalk_notify_app_key": "svc-key-only"}),
        content_type="application/json",
    )

    response = settings_api._update_settings(  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
        request,
        actor_id="admin",
    )

    assert response.status_code == HTTPStatus.OK
    assert invalidated == []
