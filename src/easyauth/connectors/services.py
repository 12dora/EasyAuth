from __future__ import annotations

from typing import TYPE_CHECKING, Final

from django.core.cache import cache
from django.utils import timezone

from easyauth.connectors.base import (
    ConnectorError,
    DesiredState,
    DesiredUserProfile,
    ReconcileReport,
)
from easyauth.connectors.models import (
    SYNC_RUN_STATUS_FAILED,
    ConnectorInstance,
    ConnectorMapping,
    ConnectorSyncRun,
)
from easyauth.connectors.registry import get_connector
from easyauth.grants.models import GRANT_STATUS_ACTIVE, AccessGrantGroup

if TYPE_CHECKING:
    from datetime import datetime

# 实例级分布式锁: 事件快路径与周期对账并发时只放行一个; 被跳过的一方不补偿——
# 对账幂等且周期兜底, 最终一致(方案 §8 双写竞态对策)。TTL 必须大于最慢一轮对账。
RECONCILE_LOCK_CACHE_KEY_TEMPLATE: Final = "easyauth:connectors:reconcile-lock:{instance_id}"
RECONCILE_LOCK_TTL_SECONDS: Final = 600

CONNECTOR_NOT_REGISTERED_TEMPLATE: Final = "连接器类型 {key} 未在 EASYAUTH_CONNECTORS 注册。"

# 健康面板判定阈值: 连续失败达到该值视为不健康(方案 §3.6)。
CONNECTOR_UNHEALTHY_FAILURE_THRESHOLD: Final = 3


def build_desired_state(instance: ConnectorInstance) -> DesiredState:
    """由框架统一构建 desired state, 连接器不直接查 grant 表(只读投影边界)。

    对该 App 全部 is_current=True 且 status=active 的 AccessGrant, 经 ConnectorMapping
    把 AccessGrantGroup 引用的授权组映射为外部组 ref。v1 只支持授权组级映射;
    未映射的授权组与散装 permission 不参与投影。
    """
    mappings = tuple(
        ConnectorMapping.objects.filter(instance=instance).select_related("authorization_group"),
    )
    external_ref_by_group_id = {
        mapping.authorization_group_id: mapping.external_ref for mapping in mappings
    }
    membership_rows = (
        AccessGrantGroup.objects.filter(
            grant__app_id=instance.app_id,
            grant__is_current=True,
            grant__status=GRANT_STATUS_ACTIVE,
            authorization_group_id__in=external_ref_by_group_id,
        )
        .select_related("grant__user")
        .order_by("id")
    )
    user_group_refs: dict[str, set[str]] = {}
    profiles: dict[str, DesiredUserProfile] = {}
    for row in membership_rows:
        user = row.grant.user
        refs = user_group_refs.setdefault(user.authentik_user_id, set())
        refs.add(external_ref_by_group_id[row.authorization_group_id])
        profiles[user.authentik_user_id] = DesiredUserProfile(
            user_id=user.authentik_user_id,
            name=user.name,
            email=user.email,
        )
    return DesiredState(
        user_groups={user_id: frozenset(refs) for user_id, refs in user_group_refs.items()},
        profiles=profiles,
        managed_group_refs=frozenset(external_ref_by_group_id.values()),
        auto_create_group_refs=frozenset(
            mapping.external_ref for mapping in mappings if mapping.auto_create
        ),
    )


def reconcile_instance(instance_id: int, *, trigger: str) -> ConnectorSyncRun | None:
    """执行一轮全量对账并记录运行审计; 实例不存在/未启用/未拿到锁时跳过。"""
    instance = (
        ConnectorInstance.objects.select_related("app").filter(id=instance_id, enabled=True).first()
    )
    if instance is None:
        return None
    lock_key = RECONCILE_LOCK_CACHE_KEY_TEMPLATE.format(instance_id=instance_id)
    if not cache.add(lock_key, "1", timeout=RECONCILE_LOCK_TTL_SECONDS):
        return None
    try:
        return _reconcile_locked(instance, trigger=trigger)
    finally:
        _ = cache.delete(lock_key)


def record_sync_run(
    instance: ConnectorInstance,
    *,
    trigger: str,
    started_at: datetime,
    report: ReconcileReport,
    update_health: bool = True,
) -> ConnectorSyncRun:
    run = ConnectorSyncRun.objects.create(
        instance=instance,
        trigger=trigger,
        started_at=started_at,
        finished_at=timezone.now(),
        status=report.status,
        stats=dict(report.stats),
        error=report.error,
    )
    # 健康字段只跟踪对账状态(离职快路径等旁路动作只留运行审计, 不改健康)。
    if not update_health:
        return run
    # 失败才累计 consecutive_failures(partial 仍在推进收敛, 不计入);
    # last_reconcile_at 无论成败都推进, 避免失败实例被调度器每分钟热循环重试。
    if report.status == SYNC_RUN_STATUS_FAILED:
        instance.consecutive_failures += 1
    else:
        instance.consecutive_failures = 0
    instance.last_reconcile_at = run.finished_at
    instance.last_status = report.status
    instance.last_error = report.error
    instance.save(
        update_fields=[
            "consecutive_failures",
            "last_reconcile_at",
            "last_status",
            "last_error",
            "updated_at",
        ],
    )
    return run


def _reconcile_locked(instance: ConnectorInstance, *, trigger: str) -> ConnectorSyncRun:
    started_at = timezone.now()
    connector = get_connector(instance.connector_key)
    if connector is None:
        report = ReconcileReport(
            status=SYNC_RUN_STATUS_FAILED,
            error=CONNECTOR_NOT_REGISTERED_TEMPLATE.format(key=instance.connector_key),
        )
        return record_sync_run(instance, trigger=trigger, started_at=started_at, report=report)
    desired = build_desired_state(instance)
    try:
        report = connector.reconcile(instance, desired)
    except ConnectorError as error:
        report = ReconcileReport(status=SYNC_RUN_STATUS_FAILED, error=str(error))
    return record_sync_run(instance, trigger=trigger, started_at=started_at, report=report)
