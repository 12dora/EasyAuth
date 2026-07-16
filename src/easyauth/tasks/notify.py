from __future__ import annotations

from typing import Final

from celery import shared_task

from easyauth.notify.services import (
    NOTIFY_DELIVERY_TASK_NAME,
    NOTIFY_PRUNE_TASK_NAME,
    NOTIFY_RECONCILE_TASK_NAME,
    deliver_message,
    prune_messages,
    reconcile_send_results,
)

# 单轮最多 5 批 x 钉钉 ~5s 超时 + 余量(第 3 篇 §1)。
_DELIVER_SOFT_TIME_LIMIT: Final = 25
_DELIVER_TIME_LIMIT: Final = 30


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
    return reconcile_send_results()


@shared_task(name=NOTIFY_PRUNE_TASK_NAME)
def prune_messages_task() -> int:
    return prune_messages()
