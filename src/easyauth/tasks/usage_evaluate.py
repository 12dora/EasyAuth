from __future__ import annotations

import logging
from time import monotonic
from typing import TYPE_CHECKING, Final

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from easyauth.usage.alerts import run
from easyauth.usage.config import load
from easyauth.usage.enforcement import evaluate

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.usage.enforcement_state import EnforcementState

logger = logging.getLogger(__name__)

USAGE_EVALUATE_TASK_NAME: Final = "easyauth.usage.evaluate"
EVALUATE_RUN_LOCK_KEY: Final = "usage:evaluate:lock"
EVALUATE_RUN_LOCK_TTL_SECONDS: Final = 120
EVALUATE_LOCK_RELEASE_SLACK_SECONDS: Final = 5
EVALUATE_SKIPPED_RESULT: Final = "skipped"


def evaluate_usage(now: datetime | None = None) -> EnforcementState:
    current = timezone.now() if now is None else now
    config = load()
    state = evaluate(current)
    _ = run(current, config, state)
    return state


@shared_task(name=USAGE_EVALUATE_TASK_NAME)
def evaluate_usage_task() -> str:
    acquired = cache.add(
        EVALUATE_RUN_LOCK_KEY,
        "1",
        timeout=EVALUATE_RUN_LOCK_TTL_SECONDS,
    )
    if not acquired:
        logger.debug("用量评估已有执行中的任务, 跳过本轮。")
        return EVALUATE_SKIPPED_RESULT
    # 超过 TTL 后锁可能已属下一轮, finally 不再删除。
    release_before = monotonic() + (
        EVALUATE_RUN_LOCK_TTL_SECONDS - EVALUATE_LOCK_RELEASE_SLACK_SECONDS
    )
    try:
        state = evaluate_usage()
    finally:
        if monotonic() < release_before:
            _ = cache.delete(EVALUATE_RUN_LOCK_KEY)
    return state.metrics["api"].state
