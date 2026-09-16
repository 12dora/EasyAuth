from __future__ import annotations

from http import HTTPStatus
from json import dumps

import pytest
from django.test import RequestFactory

from easyauth.admin_console import settings_api
from easyauth.applications.integration_settings import IntegrationSettings

pytestmark = pytest.mark.django_db(transaction=True)


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
