from __future__ import annotations

from typing import TYPE_CHECKING, Final

from celery import shared_task
from django.utils import timezone

from easyauth.usage.alerts import run
from easyauth.usage.config import load
from easyauth.usage.enforcement import EnforcementState, evaluate

if TYPE_CHECKING:
    from datetime import datetime

USAGE_EVALUATE_TASK_NAME: Final = "easyauth.usage.evaluate"


def evaluate_usage(now: datetime | None = None) -> EnforcementState:
    current = timezone.now() if now is None else now
    config = load()
    state = evaluate(current)
    _ = run(current, config, state)
    return state


@shared_task(name=USAGE_EVALUATE_TASK_NAME)
def evaluate_usage_task() -> str:
    state = evaluate_usage()
    api = state.metrics["api"]
    return api.state
