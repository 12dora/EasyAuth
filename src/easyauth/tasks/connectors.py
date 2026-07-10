from __future__ import annotations

from typing import Final

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.connectors.base import ConnectorError, ReconcileReport
from easyauth.connectors.dispatch import (
    OFFBOARD_TASK_NAME,
    RECONCILE_TASK_NAME,
    reconcile_pending_cache_key,
    request_instance_reconcile,
)
from easyauth.connectors.models import (
    SYNC_RUN_STATUS_FAILED,
    SYNC_RUN_STATUS_SUCCESS,
    SYNC_TRIGGER_OFFBOARD,
    SYNC_TRIGGER_PERIODIC,
    ConnectorInstance,
    ConnectorSyncRun,
)
from easyauth.connectors.registry import get_connector
from easyauth.connectors.services import reconcile_instance, record_sync_run

SCHEDULE_RECONCILES_TASK_NAME: Final = "easyauth.connectors.schedule_reconciles"
PRUNE_SYNC_RUNS_TASK_NAME: Final = "easyauth.connectors.prune_sync_runs"

# 每实例保留的运行记录条数(方案 §3.3: 保留最近 N 条)。
SYNC_RUN_RETENTION_PER_INSTANCE: Final = 200


@shared_task(name=RECONCILE_TASK_NAME, acks_late=True)
def reconcile_connector_instance_task(instance_id: int, trigger: str) -> str:
    # 先清除去抖 pending 标记再对账: 此后到达的事件会重新排队, 不会被本轮已经
    # 开始构建的 desired state 错过(对齐钉钉 Stream 合流模式)。
    _ = cache.delete(reconcile_pending_cache_key(instance_id))
    run = reconcile_instance(instance_id, trigger=trigger)
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
    """离职快路径: 对全部启用实例执行 on_user_offboarded; 未实现的连接器回退为对账。"""
    user = UserMirror.objects.filter(authentik_user_id=authentik_user_id).first()
    if user is None:
        return 0
    handled = 0
    for instance in ConnectorInstance.objects.filter(enabled=True).select_related("app"):
        connector = get_connector(instance.connector_key)
        if connector is None:
            continue
        started_at = timezone.now()
        try:
            if not connector.on_user_offboarded(instance, user):
                _ = request_instance_reconcile(instance.id, trigger=SYNC_TRIGGER_OFFBOARD)
                continue
        except ConnectorError as error:
            # 快路径失败不重试(周期对账兜底), 但要在运行审计里留痕。
            _ = record_sync_run(
                instance,
                trigger=SYNC_TRIGGER_OFFBOARD,
                started_at=started_at,
                report=ReconcileReport(status=SYNC_RUN_STATUS_FAILED, error=str(error)),
                update_health=False,
            )
            continue
        _ = record_sync_run(
            instance,
            trigger=SYNC_TRIGGER_OFFBOARD,
            started_at=started_at,
            report=ReconcileReport(
                status=SYNC_RUN_STATUS_SUCCESS,
                stats={"offboarded_users": 1},
            ),
            update_health=False,
        )
        handled += 1
    return handled
