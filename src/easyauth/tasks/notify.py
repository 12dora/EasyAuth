from __future__ import annotations

from time import monotonic
from typing import Final

from celery import shared_task
from django.core.cache import cache

from easyauth.notify.contracts import (
    NOTIFY_DELIVERY_TASK_NAME,
    NOTIFY_PRUNE_TASK_NAME,
    NOTIFY_RECONCILE_TASK_NAME,
)
from easyauth.notify.delivery import deliver_message
from easyauth.notify.reconciliation import reconcile_send_results
from easyauth.notify.retention import prune_messages

# 单轮最多 5 批 x 钉钉 ~5s 超时 + 余量。
_DELIVER_SOFT_TIME_LIMIT: Final = 25
_DELIVER_TIME_LIMIT: Final = 30
# 50 task x 2 次 HTTP x 5s 超时 + 余量, 略高于最坏一轮。
NOTIFY_RECONCILE_RUN_LOCK_KEY: Final = "easyauth.notify.reconcile_send_results:lock"
NOTIFY_RECONCILE_RUN_LOCK_TTL_SECONDS: Final = 600
_LOCK_RELEASE_SLACK_SECONDS: Final = 3


@shared_task(
    name=NOTIFY_DELIVERY_TASK_NAME,
    acks_late=True,
    soft_time_limit=_DELIVER_SOFT_TIME_LIMIT,
    time_limit=_DELIVER_TIME_LIMIT,
)  # pyright: ignore[reportCallIssue, reportUntypedFunctionDecorator]
def deliver_message_task(message_id: str, generation: int) -> None:
    deliver_message(message_id, generation)


@shared_task(name=NOTIFY_RECONCILE_TASK_NAME)
def reconcile_send_results_task() -> int:
    return _reconcile_with_run_lock()


def _reconcile_with_run_lock() -> int:
    acquired = cache.add(
        NOTIFY_RECONCILE_RUN_LOCK_KEY,
        "1",
        timeout=NOTIFY_RECONCILE_RUN_LOCK_TTL_SECONDS,
    )
    if not acquired:
        return 0
    release_before = (
        monotonic() + NOTIFY_RECONCILE_RUN_LOCK_TTL_SECONDS - _LOCK_RELEASE_SLACK_SECONDS
    )
    try:
        return reconcile_send_results()
    finally:
        if monotonic() < release_before:
            _ = cache.delete(NOTIFY_RECONCILE_RUN_LOCK_KEY)


@shared_task(name=NOTIFY_PRUNE_TASK_NAME)
def prune_messages_task() -> int:
    return prune_messages()
