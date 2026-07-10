from __future__ import annotations

from datetime import timedelta
from typing import Final

from celery import shared_task
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.connectors.dispatch import (
    OFFBOARD_TASK_NAME,
    RECONCILE_TASK_NAME,
    request_instance_reconcile,
)
from easyauth.connectors.models import (
    SYNC_TRIGGER_OFFBOARD,
    SYNC_TRIGGER_PERIODIC,
    ConnectorInstance,
    ConnectorSyncRun,
)
from easyauth.connectors.services import (
    RECONCILE_QUEUE_CLAIM_TIMEOUT_SECONDS,
    reconcile_instance,
)

SCHEDULE_RECONCILES_TASK_NAME: Final = "easyauth.connectors.schedule_reconciles"
PRUNE_SYNC_RUNS_TASK_NAME: Final = "easyauth.connectors.prune_sync_runs"

# 每实例保留的运行记录条数(方案 §3.3: 保留最近 N 条)。
SYNC_RUN_RETENTION_PER_INSTANCE: Final = 200
RECONCILE_TASK_SOFT_TIME_LIMIT_SECONDS: Final = 840
RECONCILE_TASK_TIME_LIMIT_SECONDS: Final = 900


@shared_task(
    name=RECONCILE_TASK_NAME,
    acks_late=True,
    soft_time_limit=RECONCILE_TASK_SOFT_TIME_LIMIT_SECONDS,
    time_limit=RECONCILE_TASK_TIME_LIMIT_SECONDS,
)  # pyright: ignore[reportCallIssue, reportUntypedFunctionDecorator]
def reconcile_connector_instance_task(instance_id: int) -> str:
    run = reconcile_instance(instance_id)
    if run is None:
        return "skipped"
    return run.status


@shared_task(name=SCHEDULE_RECONCILES_TASK_NAME)
def schedule_connector_reconciles_task() -> int:
    # 周期调度器(beat 每 60 秒): 扫描到期实例逐个入队; 入队走去抖通道,
    # 与事件快路径共用 pending 标记, 天然防重复排队。
    now = timezone.now()
    queued = 0
    for instance in ConnectorInstance.objects.filter(enabled=True):
        lease_active = (
            instance.reconcile_lease_token is not None
            and instance.reconcile_lease_expires_at is not None
            and instance.reconcile_lease_expires_at > now
        )
        queue_stale = (
            instance.reconcile_worker_queued_at is None
            or instance.reconcile_worker_queued_at
            <= now - timedelta(seconds=RECONCILE_QUEUE_CLAIM_TIMEOUT_SECONDS)
        )
        if instance.reconcile_dirty:
            if not lease_active and queue_stale and request_instance_reconcile(
                instance.id,
                trigger=SYNC_TRIGGER_PERIODIC,
                countdown=0,
            ):
                queued += 1
            continue
        last = instance.last_reconcile_at
        interval = instance.reconcile_interval_seconds
        if last is not None and (now - last).total_seconds() < interval:
            continue
        if request_instance_reconcile(instance.id, trigger=SYNC_TRIGGER_PERIODIC, countdown=0):
            queued += 1
    return queued


@shared_task(name=PRUNE_SYNC_RUNS_TASK_NAME)
def prune_connector_sync_runs_task() -> int:
    pruned = 0
    for instance in ConnectorInstance.objects.only("id"):
        # 默认排序 -started_at: 保留窗口之后的切片即最旧记录。
        stale_runs = ConnectorSyncRun.objects.filter(instance_id=instance.id).only("id")[
            SYNC_RUN_RETENTION_PER_INSTANCE:
        ]
        stale_ids = [run.id for run in stale_runs]
        if not stale_ids:
            continue
        deleted, _ = ConnectorSyncRun.objects.filter(id__in=stale_ids).delete()
        pruned += deleted
    return pruned


@shared_task(name=OFFBOARD_TASK_NAME, acks_late=True)
def offboard_user_task(authentik_user_id: str) -> int:
    """离职与普通对账共用 generation/lease 状态机, 禁止旁路写外部系统。"""
    user = UserMirror.objects.filter(authentik_user_id=authentik_user_id).first()
    if user is None:
        return 0
    instances = list(ConnectorInstance.objects.filter(enabled=True).only("id"))
    for instance in instances:
        _ = request_instance_reconcile(
            instance.id,
            trigger=SYNC_TRIGGER_OFFBOARD,
            countdown=0,
        )
    return len(instances)
