"""§7 beat 任务: 空跑 + 有行种子路径。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.lifecycle.models import (
    ASSIGNEE_STATE_MANAGER,
    HANDOVER_KIND_OFFBOARD,
    HandoverTask,
    TASK_STATUS_PENDING,
)
from easyauth.outbox.models import OutboxEvent
from easyauth.tasks.lifecycle import (
    lifecycle_daily_reminder_task,
    lifecycle_escalation_task,
    lifecycle_poll_async_actions_task,
    lifecycle_recover_expired_execution_leases_task,
    lifecycle_send_reminder_task,
)

pytestmark = pytest.mark.django_db


def test_escalation_empty() -> None:
    result = lifecycle_escalation_task()
    assert result["processed"] == 0
    assert result["errors"] == 0


def test_escalation_processes_overdue_task() -> None:
    subject = UserMirror.objects.create(
        authentik_user_id="beat-esc-sub",
        name="s",
        status=USER_STATUS_ACTIVE,
        dingtalk_source_slug="s",
        dingtalk_corp_id="c",
        dingtalk_userid="s",
    )
    assignee = UserMirror.objects.create(
        authentik_user_id="beat-esc-asg",
        name="a",
        status=USER_STATUS_ACTIVE,
        dingtalk_source_slug="s",
        dingtalk_corp_id="c",
        dingtalk_userid="a",
    )
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        assignee=assignee,
        assignee_state=ASSIGNEE_STATE_MANAGER,
        status=TASK_STATUS_PENDING,
        escalation_level=0,
        escalation_deadline=timezone.now() - timedelta(minutes=1),
    )
    result = lifecycle_escalation_task()
    assert result["processed"] == 1
    assert result["errors"] == 0
    task.refresh_from_db()
    assert task.escalation_level >= 1 or task.assignee_state == "superuser_pool"


def test_daily_reminder_empty() -> None:
    result = lifecycle_daily_reminder_task()
    assert result["claimed"] == 0


def test_daily_reminder_claims_once_and_enqueues_dedup_key() -> None:
    subject = UserMirror.objects.create(
        authentik_user_id="beat-rem-sub",
        name="s",
        status=USER_STATUS_ACTIVE,
    )
    assignee = UserMirror.objects.create(
        authentik_user_id="beat-rem-asg",
        name="a",
        status=USER_STATUS_ACTIVE,
    )
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        assignee=assignee,
        assignee_state=ASSIGNEE_STATE_MANAGER,
        status=TASK_STATUS_PENDING,
        escalation_deadline=timezone.now() + timedelta(days=5),
    )
    first = lifecycle_daily_reminder_task()
    assert first["claimed"] == 1
    assert first["enqueued"] >= 1
    business_date = timezone.localdate()
    daily_key = f"handover:{task.id}:{business_date.isoformat()}:daily"
    assert OutboxEvent.objects.filter(event_key=daily_key).exists()

    second = lifecycle_daily_reminder_task()
    assert second["claimed"] == 0
    assert OutboxEvent.objects.filter(event_key=daily_key).count() == 1


def test_send_reminder_task_raises_when_notify_identity_missing() -> None:
    """缺 easyauth-lifecycle 身份时必须失败, 使 outbox 保持未发布并重试。"""
    subject = UserMirror.objects.create(
        authentik_user_id="beat-send-sub",
        name="s",
        status=USER_STATUS_ACTIVE,
    )
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        status=TASK_STATUS_PENDING,
    )
    with pytest.raises(RuntimeError, match="notify identity not provisioned"):
        _ = lifecycle_send_reminder_task(
            task_id=task.id,
            kind="daily",
            assignee_user_id="x",
        )


def test_recover_leases_empty() -> None:
    result = lifecycle_recover_expired_execution_leases_task()
    assert result["scanned"] == 0


def test_poll_async_empty() -> None:
    result = lifecycle_poll_async_actions_task()
    assert result["scanned"] == 0


def test_beat_schedule_registers_lifecycle_entries() -> None:
    """默认 daily 必须是 crontab(09:00) 且 CELERY_TIMEZONE=Asia/Shanghai。

    不得写成 ``isinstance(daily, (float, crontab))`` 这种两边都过的假钉扎:
    若默认退回 float(86400), 本用例必须红。
    """
    import os

    from celery.schedules import crontab
    from django.conf import settings

    assert not os.environ.get(
        "EASYAUTH_LIFECYCLE_DAILY_REMINDER_SECONDS",
    ), "测试进程不得设置 EASYAUTH_LIFECYCLE_DAILY_REMINDER_SECONDS, 否则无法钉扎默认 crontab"
    keys = set(settings.CELERY_BEAT_SCHEDULE)
    assert "lifecycle-escalation" in keys
    assert "lifecycle-daily-reminder" in keys
    assert "lifecycle-recover-execution-leases" in keys
    assert "lifecycle-poll-async-actions" in keys
    assert settings.CELERY_TIMEZONE == "Asia/Shanghai"
    daily = settings.CELERY_BEAT_SCHEDULE["lifecycle-daily-reminder"]["schedule"]
    assert isinstance(daily, crontab), f"expected crontab, got {type(daily)}: {daily!r}"
    assert daily.hour == {9}
    assert daily.minute == {0}
