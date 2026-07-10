from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import transaction
from django.utils import timezone

from easyauth.outbox.models import (
    OUTBOX_STATUS_IN_FLIGHT,
    OUTBOX_STATUS_PENDING,
    OUTBOX_STATUS_PUBLISHED,
    OutboxEvent,
)
from easyauth.outbox.services import (
    OUTBOX_RETRY_BASE_SECONDS,
    OutboxEventConflictError,
    dispatch_pending_events,
    enqueue_task,
)

pytestmark = pytest.mark.django_db

ROLLBACK_MESSAGE = "回滚业务事务"
BROKER_ERROR = "broker unavailable"
RECOVERED_ATTEMPTS = 2


@pytest.fixture(autouse=True)
def isolate_outbox_events() -> None:
    # 全量回归中 transaction=True 用例可能留下待处理事件; 本模块只验证本用例创建的批次。
    _ = OutboxEvent.objects.all().delete()


def _enqueue_then_fail() -> None:
    with transaction.atomic():
        _ = enqueue_task(
            event_key="test:rollback",
            task_name="easyauth.test.task",
            args=[1],
        )
        raise RuntimeError(ROLLBACK_MESSAGE)


def test_enqueue_is_atomic_with_business_transaction() -> None:
    with pytest.raises(RuntimeError, match=ROLLBACK_MESSAGE):
        _enqueue_then_fail()

    assert not OutboxEvent.objects.filter(event_key="test:rollback").exists()


def test_enqueue_repairs_missing_event_and_is_idempotent() -> None:
    first = enqueue_task(
        event_key="test:one",
        task_name="easyauth.test.task",
        args=[1, "a"],
        kwargs={"enabled": True},
    )
    second = enqueue_task(
        event_key="test:one",
        task_name="easyauth.test.task",
        args=[1, "a"],
        kwargs={"enabled": True},
    )

    assert first.id == second.id
    assert OutboxEvent.objects.filter(event_key="test:one").count() == 1


def test_enqueue_rejects_event_key_payload_conflict() -> None:
    _ = enqueue_task(event_key="test:conflict", task_name="task.one", args=[1])

    with pytest.raises(OutboxEventConflictError):
        _ = enqueue_task(event_key="test:conflict", task_name="task.two", args=[1])


def test_dispatch_claims_and_marks_event_published() -> None:
    event = enqueue_task(event_key="test:publish", task_name="task.publish", args=[7])
    sent: list[tuple[str, list[object], dict[str, object]]] = []

    def send_task(
        task_name: str,
        *,
        args: list[object],
        kwargs: dict[str, object],
    ) -> object:
        sent.append((task_name, args, kwargs))
        return object()

    result = dispatch_pending_events(send_task=send_task)

    event.refresh_from_db()
    assert result.claimed == result.published == 1
    assert result.failed == 0
    assert sent == [("task.publish", [7], {})]
    assert event.status == OUTBOX_STATUS_PUBLISHED
    assert event.attempts == 1
    assert event.lease_token == ""
    assert event.published_at is not None


def test_dispatch_failure_persists_retry_without_losing_event() -> None:
    event = enqueue_task(event_key="test:retry", task_name="task.retry")
    now = timezone.now()

    def fail_send_task(
        _task_name: str,
        *,
        args: list[object],
        kwargs: dict[str, object],
    ) -> object:
        _ = (args, kwargs)
        raise RuntimeError(BROKER_ERROR)

    result = dispatch_pending_events(now=now, send_task=fail_send_task)

    event.refresh_from_db()
    assert result.failed == 1
    assert event.status == OUTBOX_STATUS_PENDING
    assert event.last_error == BROKER_ERROR
    assert event.available_at == now + timedelta(seconds=OUTBOX_RETRY_BASE_SECONDS)
    assert event.lease_token == ""
    assert event.lease_expires_at is None


def test_dispatch_recovers_expired_in_flight_lease() -> None:
    now = timezone.now()
    event = OutboxEvent.objects.create(
        event_key="test:expired-lease",
        task_name="task.recover",
        status=OUTBOX_STATUS_IN_FLIGHT,
        attempts=1,
        lease_token="dead-worker",  # noqa: S106 - outbox claim token, 不是密码。
        lease_expires_at=now - timedelta(seconds=1),
    )
    sent: list[str] = []

    def send_task(
        task_name: str,
        *,
        args: list[object],
        kwargs: dict[str, object],
    ) -> object:
        _ = (args, kwargs)
        sent.append(task_name)
        return object()

    result = dispatch_pending_events(now=now, send_task=send_task)

    event.refresh_from_db()
    assert result.published == 1
    assert sent == ["task.recover"]
    assert event.status == OUTBOX_STATUS_PUBLISHED
    assert event.attempts == RECOVERED_ATTEMPTS


def test_dispatch_does_not_reclaim_active_lease_or_future_event() -> None:
    now = timezone.now()
    _ = OutboxEvent.objects.create(
        event_key="test:active-lease",
        task_name="task.active",
        status=OUTBOX_STATUS_IN_FLIGHT,
        lease_token="live-worker",  # noqa: S106 - outbox claim token, 不是密码。
        lease_expires_at=now + timedelta(seconds=1),
    )
    _ = OutboxEvent.objects.create(
        event_key="test:future",
        task_name="task.future",
        available_at=now + timedelta(seconds=1),
    )

    result = dispatch_pending_events(now=now, send_task=lambda *_args, **_kwargs: object())

    assert result.claimed == 0
