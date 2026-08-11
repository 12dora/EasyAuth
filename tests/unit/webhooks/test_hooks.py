from __future__ import annotations

import hashlib
import hmac
import json
from http import HTTPStatus

import pytest

from easyauth.applications.models import App
from easyauth.webhooks import hooks as hooks_module
from easyauth.webhooks.hooks import HookCallError, signed_hook_get, signed_hook_post
from easyauth.webhooks.models import AppWebhookConfig
from easyauth.webhooks.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER
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


@pytest.mark.parametrize(
    "event_type",
    [
        "lifecycle.handover.preview",
        "lifecycle.handover.items",
        "lifecycle.handover.execute",
        "webhook.test",
    ],
)
def test_signed_hook_post_injects_event_type_into_signed_body(
    configured_app: App,
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
) -> None:
    """四种事件的 raw body 都必须含 event_type, 且签名覆盖注入后的字节。"""
    captured: dict[str, object] = {}

    def fake_post_webhook(**kwargs: object) -> WebhookHttpResponse:
        captured["headers"] = kwargs["headers"]
        captured["body"] = kwargs["body"]
        return WebhookHttpResponse(
            status_code=HTTPStatus.OK,
            body=b'{"ok":true}',
            location="",
        )

    monkeypatch.setattr(hooks_module, "post_webhook", fake_post_webhook)

    _ = signed_hook_post(
        app=configured_app,
        url="https://hooks.example.com/handover",
        event_type=event_type,
        delivery_id=f"hook-et-{event_type}",
        payload={"task_id": "137:4"},
    )

    body = captured["body"]
    assert isinstance(body, bytes)
    parsed = json.loads(body.decode("utf-8"))
    assert parsed["event_type"] == event_type
    assert parsed["task_id"] == "137:4"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    timestamp = headers[TIMESTAMP_HEADER]
    expected = hmac.new(
        b"whsec_hooks_test",
        timestamp.encode("utf-8") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    assert headers[SIGNATURE_HEADER] == expected


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


def test_signed_hook_post_preserves_non_2xx_error_body(
    configured_app: App,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post_webhook(**_kwargs: object) -> WebhookHttpResponse:
        return WebhookHttpResponse(
            status_code=HTTPStatus.BAD_REQUEST,
            body=b'{"error":{"code":"timestamp_out_of_range","message":"expired","traceId":"t1"}}',
            location="",
        )

    monkeypatch.setattr(hooks_module, "post_webhook", fake_post_webhook)

    with pytest.raises(HookCallError) as exc_info:
        _ = signed_hook_post(
            app=configured_app,
            url="https://hooks.example.com/handover",
            event_type="lifecycle.handover.execute",
            delivery_id="hook-error-body",
            payload={},
        )

    assert exc_info.value.status_code == HTTPStatus.BAD_REQUEST
    assert exc_info.value.payload is not None
    assert exc_info.value.payload["error"] == {
        "code": "timestamp_out_of_range",
        "message": "expired",
        "traceId": "t1",
    }
    assert "timestamp_out_of_range" in exc_info.value.raw_body


def test_signed_hook_post_captures_retry_after(
    configured_app: App,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post_webhook(**_kwargs: object) -> WebhookHttpResponse:
        return WebhookHttpResponse(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            body=b'{"detail":{"code":"RATE_LIMITED"}}',
            location="",
            retry_after="120",
        )

    monkeypatch.setattr(hooks_module, "post_webhook", fake_post_webhook)
    with pytest.raises(HookCallError) as exc_info:
        _ = signed_hook_post(
            app=configured_app,
            url="https://hooks.example.com/handover",
            event_type="lifecycle.handover.preview",
            delivery_id="hook-rate-limit",
            payload={},
        )
    assert exc_info.value.retry_after_seconds == 120


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
