from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from celery import current_app
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from easyauth.outbox.models import (
    OUTBOX_STATUS_IN_FLIGHT,
    OUTBOX_STATUS_PENDING,
    OUTBOX_STATUS_PUBLISHED,
    OutboxEvent,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from easyauth.applications.ops_models import JsonValue

OUTBOX_EVENT_CONFLICT_MESSAGE: Final = "同一 outbox event_key 已绑定不同任务载荷。"
OUTBOX_DEFAULT_BATCH_SIZE: Final = 100
OUTBOX_LEASE_SECONDS: Final = 60
OUTBOX_RETRY_BASE_SECONDS: Final = 5
OUTBOX_RETRY_MAX_SECONDS: Final = 300

type SendTask = Callable[..., object]


class OutboxEventConflictError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(OUTBOX_EVENT_CONFLICT_MESSAGE)


@dataclass(frozen=True, slots=True)
class DispatchResult:
    claimed: int
    published: int
    failed: int


def enqueue_task(
    *,
    event_key: str,
    task_name: str,
    args: Sequence[JsonValue] = (),
    kwargs: dict[str, JsonValue] | None = None,
    countdown: float = 0,
) -> OutboxEvent:
    """幂等写入任务事件, 调用方应在业务事实所在事务内调用。"""
    available_at = timezone.now() + timedelta(seconds=countdown)
    normalized_args = list(args)
    normalized_kwargs = dict(kwargs or {})
    event, _created = OutboxEvent.objects.get_or_create(
        event_key=event_key,
        defaults={
            "task_name": task_name,
            "args": normalized_args,
            "kwargs": normalized_kwargs,
            "available_at": available_at,
        },
    )
    if (
        event.task_name != task_name
        or event.args != normalized_args
        or event.kwargs != normalized_kwargs
    ):
        raise OutboxEventConflictError
    return event


def dispatch_pending_events(
    *,
    batch_size: int = OUTBOX_DEFAULT_BATCH_SIZE,
    lease_seconds: int = OUTBOX_LEASE_SECONDS,
    now: datetime | None = None,
    send_task: SendTask | None = None,
) -> DispatchResult:
    """抢占并发布一批到期事件, 过期 in-flight 会自动恢复。"""
    dispatch_time = timezone.now() if now is None else now
    events = _claim_events(batch_size=batch_size, lease_seconds=lease_seconds, now=dispatch_time)
    sender = current_app.send_task if send_task is None else send_task
    published = 0
    failed = 0
    for event in events:
        try:
            _ = sender(event.task_name, args=event.args, kwargs=event.kwargs)
        except Exception as error:  # noqa: BLE001 - broker 错误必须持久化后由 scanner 重试。
            _mark_publish_failed(event, error=error, now=dispatch_time)
            failed += 1
        else:
            _mark_published(event, now=dispatch_time)
            published += 1
    return DispatchResult(claimed=len(events), published=published, failed=failed)


def _claim_events(*, batch_size: int, lease_seconds: int, now: datetime) -> list[OutboxEvent]:
    if batch_size <= 0:
        return []
    claim_token = uuid.uuid4().hex
    with transaction.atomic():
        queryset = OutboxEvent.objects.filter(
            Q(status=OUTBOX_STATUS_PENDING, available_at__lte=now)
            | Q(status=OUTBOX_STATUS_IN_FLIGHT, lease_expires_at__lte=now),
        ).order_by("created_at", "id")
        if connection.features.has_select_for_update_skip_locked:
            queryset = queryset.select_for_update(skip_locked=True)
        else:
            queryset = queryset.select_for_update()
        events = list(queryset[:batch_size])
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        for event in events:
            event.status = OUTBOX_STATUS_IN_FLIGHT
            event.attempts += 1
            event.lease_token = claim_token
            event.lease_expires_at = lease_expires_at
            event.last_error = ""
            event.updated_at = now
        if events:
            OutboxEvent.objects.bulk_update(
                events,
                fields=(
                    "status",
                    "attempts",
                    "lease_token",
                    "lease_expires_at",
                    "last_error",
                    "updated_at",
                ),
            )
    return events


def _mark_published(event: OutboxEvent, *, now: datetime) -> None:
    _ = OutboxEvent.objects.filter(
        id=event.id,
        status=OUTBOX_STATUS_IN_FLIGHT,
        lease_token=event.lease_token,
    ).update(
        status=OUTBOX_STATUS_PUBLISHED,
        lease_token="",
        lease_expires_at=None,
        published_at=now,
        updated_at=now,
    )


def _mark_publish_failed(event: OutboxEvent, *, error: Exception, now: datetime) -> None:
    retry_seconds = min(
        OUTBOX_RETRY_BASE_SECONDS * (2 ** max(event.attempts - 1, 0)),
        OUTBOX_RETRY_MAX_SECONDS,
    )
    _ = OutboxEvent.objects.filter(
        id=event.id,
        status=OUTBOX_STATUS_IN_FLIGHT,
        lease_token=event.lease_token,
    ).update(
        status=OUTBOX_STATUS_PENDING,
        available_at=now + timedelta(seconds=retry_seconds),
        lease_token="",
        lease_expires_at=None,
        last_error=str(error),
        updated_at=now,
    )
