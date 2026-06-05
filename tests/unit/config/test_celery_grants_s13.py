from __future__ import annotations

from easyauth.config.settings import test as project_settings
from easyauth.tasks.grants import GRANT_EXPIRATION_TASK_NAME


def test_s13_celery_beat_schedules_grant_expiration_cleanup() -> None:
    # Given: S13 需要 Celery beat 周期触发授权过期清理。
    schedule_name = "grant-expiration-cleanup"

    # When: 读取项目 Celery beat 配置。
    schedule = project_settings.CELERY_BEAT_SCHEDULE

    # Then: beat 调度指向 grants 清理任务。
    assert schedule[schedule_name]["task"] == GRANT_EXPIRATION_TASK_NAME
