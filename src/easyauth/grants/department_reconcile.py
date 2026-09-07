from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from easyauth.outbox.services import enqueue_task

# 部门预授权对账任务, 由目录同步完成、策略增删改与 beat 定时触发。
DEPARTMENT_GRANT_RECONCILE_TASK_NAME = "easyauth.grants.reconcile_department_grants"
_ENQUEUE_COUNTDOWN_SECONDS = 2

__all__ = [
    "DEPARTMENT_GRANT_RECONCILE_TASK_NAME",
    "schedule_department_grant_reconcile",
]


def schedule_department_grant_reconcile(*, trigger: str) -> None:
    """在当前事务提交后经 outbox 幂等入队一次全量对账。

    event_key 按 (trigger, 秒) 归并: 同一秒内的重复调用只保留一条; countdown 大于归并窗口,
    因此归并到的事件一定尚未派发, 不会漏掉窗口末尾的变更。
    """
    bucket = int(timezone.now().timestamp())
    event_key = f"department-grant-reconcile:{trigger}:{bucket}"

    def _enqueue() -> None:
        _ = enqueue_task(
            event_key=event_key,
            task_name=DEPARTMENT_GRANT_RECONCILE_TASK_NAME,
            countdown=_ENQUEUE_COUNTDOWN_SECONDS,
        )

    transaction.on_commit(_enqueue)
