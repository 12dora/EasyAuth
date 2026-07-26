from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from http import HTTPStatus
from typing import cast

import pytest
from django.utils import timezone

from easyauth.applications.models import App
from easyauth.outbox.models import OutboxEvent
from easyauth.webhooks import delivery as delivery_module
from easyauth.webhooks.delivery import (
    WebhookDeliveryAttemptError,
    WebhookNotConfiguredError,
    WebhookRedeliveryConflictError,
    attempt_delivery,
    enqueue_delivery,
    mark_delivery_exhausted,
    recover_expired_delivery_leases,
    redeliver,
)
from easyauth.webhooks.models import AppWebhookConfig, WebhookDelivery
from easyauth.webhooks.signing import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
)
from easyauth.webhooks.transport import WebhookHttpResponse, WebhookTransportError

pytestmark = pytest.mark.django_db

SECRET = "whsec_unit"  # noqa: S105 - 测试用密钥。
NEXT_GENERATION = 2
OLD_LEASE_GENERATION = 3
WATCHDOG_RECOVERY_GENERATION = 4
CONNECTION_REFUSED = "connection refused"
OLD_CLAIM_TOKEN = "old-claim"  # noqa: S105 - 测试租约令牌。
UNEXPECTED_FAILURE_MESSAGE = "boom"


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


def test_enqueue_persists_delivery_and_outbox_in_one_transaction() -> None:
    app = _configured_app("wh-outbox-app")

    delivery = enqueue_delivery(
        app=app,
        event_type="webhook.test",
        url="https://app.example.com/hook",
        payload={"id": 1},
    )

    event = OutboxEvent.objects.get(
        event_key=f"webhook-delivery:{delivery.delivery_id}:{delivery.generation}",
    )
    assert cast("list[object]", event.args) == [delivery.id, delivery.generation]
    assert event.task_name == "easyauth.webhooks.deliver"


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

    def fake_post_webhook(**kwargs: object) -> WebhookHttpResponse:
        captured["headers"] = kwargs["headers"]
        captured["body"] = kwargs["body"]
        return WebhookHttpResponse(status_code=HTTPStatus.OK, body=b"{}", location="")

    monkeypatch.setattr(delivery_module, "post_webhook", fake_post_webhook)

    # When
    result = attempt_delivery(delivery.id, delivery.generation)

    # Then: 头与签名符合 §5.1 规范, 投递翻 delivered。
    headers = cast("dict[str, str]", captured["headers"])
    body = cast("bytes", captured["body"])
    assert json.loads(body.decode("utf-8")) == {"biz_key": "order-1"}
    assert headers[EVENT_HEADER] == "approval.completed"
    assert headers[DELIVERY_HEADER] == "d-sign-1"
    timestamp = headers[TIMESTAMP_HEADER]
    assert isinstance(timestamp, str)
    expected = hmac.new(
        SECRET.encode("utf-8"),
        timestamp.encode("utf-8") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    assert headers[SIGNATURE_HEADER] == expected
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

    def fake_post_webhook(**_kwargs: object) -> WebhookHttpResponse:
        raise WebhookTransportError(CONNECTION_REFUSED)

    monkeypatch.setattr(delivery_module, "post_webhook", fake_post_webhook)

    # When / Then: 失败计数与错误落库, 异常携带 attempts 供任务层调度重试。
    with pytest.raises(WebhookDeliveryAttemptError) as exc_info:
        _ = attempt_delivery(delivery.id, delivery.generation)
    delivery.refresh_from_db()
    assert exc_info.value.attempts == 1
    assert delivery.attempts == 1
    assert delivery.status == "pending"
    assert delivery.last_error != ""
    retry_event = OutboxEvent.objects.get(
        event_key=f"webhook-delivery:{delivery.delivery_id}:{delivery.generation}:attempt:2",
    )
    assert cast("list[object]", retry_event.args) == [delivery.id, delivery.generation]

    # 判定为最终失败后状态翻 failed。
    mark_delivery_exhausted(delivery.id, delivery.generation)
    delivery.refresh_from_db()
    assert delivery.status == "failed"


def test_attempt_delivery_unexpected_error_records_recoverable_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _configured_app("wh-unexpected-app")
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="d-unexpected-1",
        event_type="webhook.test",
        target_url="https://app.example.com/hook",
        payload={},
    )

    def fake_post_webhook(**_kwargs: object) -> WebhookHttpResponse:
        raise RuntimeError(UNEXPECTED_FAILURE_MESSAGE)

    monkeypatch.setattr(delivery_module, "post_webhook", fake_post_webhook)

    with pytest.raises(WebhookDeliveryAttemptError) as exc_info:
        _ = attempt_delivery(delivery.id, delivery.generation)

    delivery.refresh_from_db()
    assert exc_info.value.attempts == 1
    assert delivery.status == "pending"
    assert delivery.claim_token == ""
    assert delivery.lease_expires_at is None
    assert "非预期异常: RuntimeError: boom" in delivery.last_error
    retry_event = OutboxEvent.objects.get(
        event_key=f"webhook-delivery:{delivery.delivery_id}:{delivery.generation}:attempt:2",
    )
    assert cast("list[object]", retry_event.args) == [delivery.id, delivery.generation]


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
    assert result.generation == NEXT_GENERATION


def test_redeliver_rejects_pending_delivery() -> None:
    app = _configured_app("wh-redeliver-pending-app")
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="d-redeliver-pending-1",
        event_type="webhook.test",
        target_url="https://app.example.com/hook",
        payload={},
    )

    with pytest.raises(WebhookRedeliveryConflictError):
        _ = redeliver(delivery)

    delivery.refresh_from_db()
    assert delivery.status == "pending"
    assert delivery.generation == 1


def test_redeliver_atomically_rejects_a_second_request() -> None:
    # Given: 两个请求都读到了同一条 failed 投递。
    app = _configured_app("wh-redeliver-race-app")
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="d-redeliver-race-1",
        event_type="webhook.test",
        target_url="https://app.example.com/hook",
        payload={},
        status="failed",
        attempts=5,
        last_error="HTTP 500",
    )
    stale_delivery = WebhookDelivery.objects.get(id=delivery.id)

    # When: 第一个请求推进成功, 第二个请求仍携带旧的 failed 对象重投。
    _ = redeliver(delivery)
    with pytest.raises(WebhookRedeliveryConflictError):
        _ = redeliver(stale_delivery)

    # Then: 数据库只保留第一次推进后的状态。
    stale_delivery.refresh_from_db()
    assert stale_delivery.status == "pending"
    assert stale_delivery.attempts == 0
    assert stale_delivery.last_error == ""


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
    result = attempt_delivery(delivery.id, delivery.generation)

    # Then
    assert result.status == "delivered"
    assert result.attempts == 1


def test_attempt_delivery_claim_prevents_duplicate_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _configured_app("wh-claim-app")
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="d-claim-1",
        event_type="webhook.test",
        target_url="https://app.example.com/hook",
        payload={},
    )
    post_count = 0

    def fake_post_webhook(**_kwargs: object) -> WebhookHttpResponse:
        nonlocal post_count
        post_count += 1
        duplicate = attempt_delivery(delivery.id, delivery.generation)
        assert duplicate.status == "pending"
        return WebhookHttpResponse(status_code=HTTPStatus.OK, body=b"{}", location="")

    monkeypatch.setattr(delivery_module, "post_webhook", fake_post_webhook)

    result = attempt_delivery(delivery.id, delivery.generation)

    assert result.status == "delivered"
    assert result.attempts == 1
    assert post_count == 1


def test_old_generation_cannot_post_or_overwrite_redelivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _configured_app("wh-generation-app")
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="d-generation-1",
        event_type="webhook.test",
        target_url="https://app.example.com/hook",
        payload={},
        status="failed",
    )
    stale_generation = delivery.generation
    _ = redeliver(delivery)

    def unexpected_post(**_kwargs: object) -> WebhookHttpResponse:
        pytest.fail("旧 generation 不得发送网络请求")

    monkeypatch.setattr(delivery_module, "post_webhook", unexpected_post)

    result = attempt_delivery(delivery.id, stale_generation)

    assert result.status == "pending"
    assert result.generation == stale_generation + 1
    assert result.attempts == 0


def test_late_success_cannot_overwrite_new_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _configured_app("wh-late-success-app")
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="d-late-success-1",
        event_type="webhook.test",
        target_url="https://app.example.com/hook",
        payload={},
    )

    def fake_post_webhook(**_kwargs: object) -> WebhookHttpResponse:
        _ = WebhookDelivery.objects.filter(id=delivery.id).update(
            status="failed",
            claim_token="",
            lease_expires_at=None,
        )
        failed = WebhookDelivery.objects.get(id=delivery.id)
        _ = redeliver(failed)
        return WebhookHttpResponse(status_code=HTTPStatus.OK, body=b"{}", location="")

    monkeypatch.setattr(delivery_module, "post_webhook", fake_post_webhook)

    result = attempt_delivery(delivery.id, delivery.generation)

    assert result.status == "pending"
    assert result.generation == NEXT_GENERATION
    assert result.attempts == 0


def test_watchdog_advances_expired_lease_and_schedules_recovery() -> None:
    app = _configured_app("wh-watchdog-app")
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="d-watchdog-1",
        event_type="webhook.test",
        target_url="https://app.example.com/hook",
        payload={},
        attempts=1,
        generation=OLD_LEASE_GENERATION,
        claim_token=OLD_CLAIM_TOKEN,
        lease_expires_at=timezone.now() - timedelta(seconds=1),
    )

    recovered = recover_expired_delivery_leases()

    assert recovered == 1
    delivery.refresh_from_db()
    assert delivery.status == "pending"
    assert delivery.attempts == 1
    assert delivery.generation == WATCHDOG_RECOVERY_GENERATION
    assert delivery.claim_token == ""
    assert delivery.lease_expires_at is None
    assert delivery.last_error == "投递租约过期, 已创建恢复尝试。"
    event = OutboxEvent.objects.get(
        event_key=f"webhook-delivery:{delivery.delivery_id}:{delivery.generation}",
    )
    assert cast("list[object]", event.args) == [delivery.id, delivery.generation]


def test_expired_lease_same_generation_waits_for_watchdog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _configured_app("wh-expired-claim-app")
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="d-expired-claim-1",
        event_type="webhook.test",
        target_url="https://app.example.com/hook",
        payload={},
        attempts=1,
        generation=OLD_LEASE_GENERATION,
        claim_token=OLD_CLAIM_TOKEN,
        lease_expires_at=timezone.now() - timedelta(seconds=1),
    )

    def unexpected_post(**_kwargs: object) -> WebhookHttpResponse:
        pytest.fail("过期租约不得被同 generation 任务自行抢占")

    monkeypatch.setattr(delivery_module, "post_webhook", unexpected_post)

    result = attempt_delivery(delivery.id, delivery.generation)

    assert result.status == "pending"
    assert result.generation == OLD_LEASE_GENERATION
    assert result.attempts == 1
    delivery.refresh_from_db()
    assert delivery.generation == OLD_LEASE_GENERATION
    assert delivery.claim_token == OLD_CLAIM_TOKEN
    assert recover_expired_delivery_leases() == 1
    delivery.refresh_from_db()
    assert delivery.generation == WATCHDOG_RECOVERY_GENERATION
    event = OutboxEvent.objects.get(
        event_key=f"webhook-delivery:{delivery.delivery_id}:{delivery.generation}",
    )
    assert cast("list[object]", event.args) == [delivery.id, delivery.generation]


def test_watchdog_ignores_unclaimed_pending_delivery() -> None:
    app = _configured_app("wh-watchdog-idle-app")
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="d-watchdog-idle-1",
        event_type="webhook.test",
        target_url="https://app.example.com/hook",
        payload={},
    )

    assert recover_expired_delivery_leases() == 0
    delivery.refresh_from_db()
    assert delivery.generation == 1
