from __future__ import annotations

from http import HTTPStatus

import pytest

from easyauth.applications.models import App
from easyauth.webhooks import hooks as hooks_module
from easyauth.webhooks.hooks import HookCallError, signed_hook_get, signed_hook_post
from easyauth.webhooks.models import AppWebhookConfig
from easyauth.webhooks.transport import WebhookHttpResponse

pytestmark = pytest.mark.django_db


@pytest.fixture
def configured_app() -> App:
    app = App.objects.create(app_key="hooks-response-app", name="Hooks")
    _ = AppWebhookConfig.objects.create(
        app=app,
        secret="whsec_hooks_test",  # noqa: S106 - 测试签名密钥。
        handover_url="https://hooks.example.com/handover",
    )

    return app


def test_signed_hook_post_preserves_202_status_and_location(
    configured_app: App,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post_webhook(**_kwargs: object) -> WebhookHttpResponse:
        return WebhookHttpResponse(
            status_code=HTTPStatus.ACCEPTED,
            body=b'{"job_id":"job-1"}',
            location="https://hooks.example.com/jobs/job-1",
        )

    monkeypatch.setattr(hooks_module, "post_webhook", fake_post_webhook)

    response = signed_hook_post(
        app=configured_app,
        url="https://hooks.example.com/handover",
        event_type="lifecycle.handover.execute",
        delivery_id="hook-1",
        payload={},
    )

    assert response.status_code == HTTPStatus.ACCEPTED
    assert response.location == "https://hooks.example.com/jobs/job-1"
    assert response.payload == {"job_id": "job-1"}


def test_signed_hook_post_rejects_redirect_without_following(
    configured_app: App,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post_webhook(**_kwargs: object) -> WebhookHttpResponse:
        return WebhookHttpResponse(
            status_code=HTTPStatus.FOUND,
            body=b"",
            location="https://attacker.example/collect",
        )

    monkeypatch.setattr(hooks_module, "post_webhook", fake_post_webhook)

    with pytest.raises(HookCallError) as exc_info:
        _ = signed_hook_post(
            app=configured_app,
            url="https://hooks.example.com/handover",
            event_type="lifecycle.handover.execute",
            delivery_id="hook-2",
            payload={},
        )

    assert exc_info.value.status_code == HTTPStatus.FOUND


def test_signed_hook_get_revalidates_location_and_preserves_202(
    configured_app: App,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_get_webhook(**kwargs: object) -> WebhookHttpResponse:
        captured.update(kwargs)
        return WebhookHttpResponse(
            status_code=HTTPStatus.ACCEPTED,
            body=b'{"state":"running"}',
            location="https://hooks.example.com/jobs/job-1",
        )

    monkeypatch.setattr(hooks_module, "get_webhook", fake_get_webhook)

    response = signed_hook_get(
        app=configured_app,
        url="https://hooks.example.com/jobs/job-1",
        event_type="lifecycle.handover.execute.status",
        delivery_id="hook-3",
    )

    assert captured["allowed_hosts"] == ("hooks.example.com",)
    assert response.status_code == HTTPStatus.ACCEPTED
    assert response.payload == {"state": "running"}
