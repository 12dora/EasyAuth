from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from easyauth.tasks import webhooks as task_module
from easyauth.webhooks.delivery import WebhookDeliveryAttemptError

if TYPE_CHECKING:
    import pytest

SOFT_TIME_LIMIT_SECONDS = 18
HARD_TIME_LIMIT_SECONDS = 20


@dataclass(frozen=True, slots=True)
class _Delivery:
    status: str


def test_delivery_task_passes_generation_to_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[int, int]] = []

    def attempt(delivery_id: int, generation: int) -> _Delivery:
        captured.append((delivery_id, generation))
        return _Delivery(status="delivered")

    monkeypatch.setattr(task_module, "attempt_delivery", attempt)

    result = task_module.deliver_webhook_task.run(11, 7)

    assert result == "delivered"
    assert captured == [(11, 7)]


def test_delivery_task_retries_same_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_attempt(_delivery_id: int, _generation: int) -> _Delivery:
        message = "delivery failed"
        raise WebhookDeliveryAttemptError(message, attempts=1)

    monkeypatch.setattr(task_module, "attempt_delivery", fail_attempt)

    result = task_module.deliver_webhook_task.run(12, 9)

    assert result == "retry_scheduled"


def test_delivery_task_has_hard_and_soft_time_limits() -> None:
    assert task_module.deliver_webhook_task.soft_time_limit == SOFT_TIME_LIMIT_SECONDS
    assert task_module.deliver_webhook_task.time_limit == HARD_TIME_LIMIT_SECONDS
