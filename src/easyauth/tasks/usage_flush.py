from __future__ import annotations

from typing import Final

from celery import shared_task

from easyauth.usage.recorder import flush_counters

FLUSH_COUNTERS_TASK_NAME: Final = "easyauth.usage.flush_counters"


@shared_task(name=FLUSH_COUNTERS_TASK_NAME)
def flush_counters_task() -> int:
    return flush_counters()
