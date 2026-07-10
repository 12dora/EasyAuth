from __future__ import annotations

from typing import Final

from celery import shared_task

from easyauth.outbox.services import dispatch_pending_events

DISPATCH_OUTBOX_TASK_NAME: Final = "easyauth.outbox.dispatch_pending"


@shared_task(name=DISPATCH_OUTBOX_TASK_NAME)
def dispatch_outbox_task() -> dict[str, int]:
    result = dispatch_pending_events()
    return {
        "claimed": result.claimed,
        "published": result.published,
        "failed": result.failed,
    }
