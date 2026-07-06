from __future__ import annotations

import hashlib
import hmac
import json
from typing import Self
from urllib.error import URLError

import pytest

from easyauth.applications.models import App
from easyauth.webhooks import delivery as delivery_module
from easyauth.webhooks.delivery import (
    WebhookDeliveryAttemptError,
    WebhookNotConfiguredError,
    attempt_delivery,
    enqueue_delivery,
    mark_delivery_exhausted,
    redeliver,
)
from easyauth.webhooks.models import AppWebhookConfig, WebhookDelivery

pytestmark = pytest.mark.django_db

SECRET = "whsec_unit"  # noqa: S105 - 测试用密钥。


class _FakeResponse:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return b"{}"


def _configured_app(app_key: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppWebhookConfig.objects.create(
        app=app,
        secret=SECRET,
        approval_callback_url="https://app.example.com/hook",
    )
    return app


def test_enqueue_requires_configured_webhook() -> None:
    # Given: 无 webhook 配置的 App。
    app = App.objects.create(app_key="wh-unconfigured", name="X")

    # When / Then
    with pytest.raises(WebhookNotConfiguredError):
        _ = enqueue_delivery(
            app=app,
            event_type="webhook.test",
            url="https://app.example.com/hook",
            payload={},
        )
    assert WebhookDelivery.objects.count() == 0


def test_attempt_delivery_signs_request_per_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: 一条 pending 投递。
    app = _configured_app("wh-sign-app")
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="d-sign-1",
        event_type="approval.completed",
        target_url="https://app.example.com/hook",
        payload={"biz_key": "order-1"},
    )
    captured: dict[str, object] = {}

    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:  # noqa: ARG001
        captured["headers"] = dict(request.headers)  # type: ignore[attr-defined]
        captured["body"] = request.data  # type: ignore[attr-defined]
        return _FakeResponse()

    monkeypatch.setattr(delivery_module, "urlopen", fake_urlopen)

    # When
    result = attempt_delivery(delivery.id)

    # Then: 头与签名符合 §5.1 规范, 投递翻 delivered。
    headers = captured["headers"]
    assert isinstance(headers, dict)
    body = captured["body"]
    assert isinstance(body, bytes)
    assert json.loads(body.decode("utf-8")) == {"biz_key": "order-1"}
    assert headers["X-easyauth-event"] == "approval.completed"
    assert headers["X-easyauth-delivery"] == "d-sign-1"
    timestamp = headers["X-easyauth-timestamp"]
    assert isinstance(timestamp, str)
    expected = hmac.new(
        SECRET.encode("utf-8"),
        timestamp.encode("utf-8") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    assert headers["X-easyauth-signature"] == expected
    assert result.status == "delivered"
    assert result.attempts == 1


def test_attempt_delivery_failure_records_error_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    app = _configured_app("wh-fail-app")
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="d-fail-1",
        event_type="webhook.test",
        target_url="https://app.example.com/hook",
        payload={},
    )

    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:  # noqa: ARG001
        reason = "connection refused"
        raise URLError(reason)

    monkeypatch.setattr(delivery_module, "urlopen", fake_urlopen)

    # When / Then: 失败计数与错误落库, 异常携带 attempts 供任务层调度重试。
    with pytest.raises(WebhookDeliveryAttemptError) as exc_info:
        _ = attempt_delivery(delivery.id)
    delivery.refresh_from_db()
    assert exc_info.value.attempts == 1
    assert delivery.attempts == 1
    assert delivery.status == "pending"
    assert delivery.last_error != ""

    # 判定为最终失败后状态翻 failed。
    mark_delivery_exhausted(delivery.id)
    delivery.refresh_from_db()
    assert delivery.status == "failed"


def test_redeliver_resets_counters() -> None:
    # Given: 一条已失败的投递。
    app = _configured_app("wh-redeliver-app")
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="d-redeliver-1",
        event_type="webhook.test",
        target_url="https://app.example.com/hook",
        payload={},
        status="failed",
        attempts=5,
        last_error="HTTP 500",
    )

    # When
    result = redeliver(delivery)

    # Then: 状态与计数重置, 重新走完整重试计划。
    assert result.status == "pending"
    assert result.attempts == 0
    assert result.last_error == ""


def test_attempt_delivery_is_idempotent_for_delivered_rows() -> None:
    # Given: 已 delivered 的投递(重复任务派发)。
    app = _configured_app("wh-idem-app")
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="d-idem-1",
        event_type="webhook.test",
        target_url="https://app.example.com/hook",
        payload={},
        status="delivered",
        attempts=1,
    )

    # When: 再次尝试(不 mock urlopen——幂等路径不应发任何请求)。
    result = attempt_delivery(delivery.id)

    # Then
    assert result.status == "delivered"
    assert result.attempts == 1
