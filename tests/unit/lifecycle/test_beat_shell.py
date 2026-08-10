"""§7 beat 任务壳可导入、可空跑。"""

from __future__ import annotations

import pytest

from easyauth.tasks.lifecycle import (
    lifecycle_daily_reminder_task,
    lifecycle_escalation_task,
    lifecycle_poll_async_actions_task,
    lifecycle_recover_expired_execution_leases_task,
)

pytestmark = pytest.mark.django_db


def test_escalation_empty() -> None:
    result = lifecycle_escalation_task()
    assert result["processed"] == 0


def test_daily_reminder_empty() -> None:
    result = lifecycle_daily_reminder_task()
    assert "claimed" in result


def test_recover_leases_empty() -> None:
    result = lifecycle_recover_expired_execution_leases_task()
    assert result["scanned"] == 0


def test_poll_async_empty() -> None:
    result = lifecycle_poll_async_actions_task()
    assert result["scanned"] == 0


def test_beat_schedule_registers_lifecycle_entries() -> None:
    from django.conf import settings

    keys = set(settings.CELERY_BEAT_SCHEDULE)
    assert "lifecycle-escalation" in keys
    assert "lifecycle-daily-reminder" in keys
    assert "lifecycle-recover-execution-leases" in keys
    assert "lifecycle-poll-async-actions" in keys
