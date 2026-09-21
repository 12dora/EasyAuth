from __future__ import annotations

import pytest
from django.utils import timezone

from easyauth.tasks.usage_flush import FLUSH_COUNTERS_TASK_NAME, flush_counters_task
from easyauth.usage.models import UsageBucket
from easyauth.usage.recorder import flush_counters, record, truncate_hour_utc
from easyauth.usage.registry import SOURCE_EASYAUTH

pytestmark = pytest.mark.django_db


def _current_bucket(category_key: str) -> UsageBucket:
    return UsageBucket.objects.get(
        hour_start=truncate_hour_utc(timezone.now()),
        source=SOURCE_EASYAUTH,
        category=category_key,
    )


def test_flush_task_name() -> None:
    assert FLUSH_COUNTERS_TASK_NAME == "easyauth.usage.flush_counters"
    assert flush_counters_task.name == FLUSH_COUNTERS_TASK_NAME


def test_flush_idempotent_and_never_decreases() -> None:
    record("notify_send")
    record("notify_send")
    assert flush_counters() == 1
    bucket = _current_bucket("notify_send")
    assert bucket.count == 2
    assert bucket.blocked_count == 0
    assert bucket.metric == "api"
    assert bucket.billed is True
    assert flush_counters() == 1
    bucket.refresh_from_db()
    assert bucket.count == 2

    bucket.count = 50
    bucket.blocked_count = 9
    bucket.save(update_fields=["count", "blocked_count", "updated_at"])
    assert flush_counters() == 1
    bucket.refresh_from_db()
    assert bucket.count == 50
    assert bucket.blocked_count == 9


def test_flush_task_writes_open_hours() -> None:
    record("approval", count=4)
    written = flush_counters_task()
    assert written == 1
    bucket = _current_bucket("approval")
    assert bucket.count == 4
    assert bucket.metric == "api"
    assert bucket.billed is True
