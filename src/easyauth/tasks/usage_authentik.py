from __future__ import annotations

from typing import Final

from celery import shared_task
from django.utils import timezone

from easyauth.usage.authentik_sync import sync

USAGE_AUTHENTIK_SYNC_TASK_NAME: Final = "easyauth.usage.sync_authentik"


@shared_task(name=USAGE_AUTHENTIK_SYNC_TASK_NAME)
def sync_authentik_task() -> None:
    # 拉取 Authentik 小时桶并回推执行策略; 失败写入 RuntimeState, 不向外抛。
    sync(timezone.now())
