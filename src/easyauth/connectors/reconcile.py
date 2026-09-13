from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.connectors.base import BaseConnector, ConnectorError, ReconcileReport
from easyauth.connectors.desired_state import build_desired_state
from easyauth.connectors.external_groups import CONNECTOR_NOT_REGISTERED_TEMPLATE
from easyauth.connectors.models import (
    SYNC_RUN_STATUS_FAILED,
    SYNC_RUN_STATUS_SUCCESS,
    SYNC_TRIGGER_OFFBOARD,
    ConnectorInstance,
    ConnectorMapping,
    ConnectorSyncRun,
)
from easyauth.connectors.registry import get_connector

if TYPE_CHECKING:
    from datetime import datetime

EXTERNAL_ACCOUNT_CHANGED_MESSAGE: Final = "连接器不可重新绑定到另一个外部账户。"
EXTERNAL_ACCOUNT_CONFLICT_MESSAGE: Final = "该外部账户已绑定到另一个 EasyAuth App。"
RECONCILE_TASK_SOFT_TIME_LIMIT_SECONDS: Final = 840
RECONCILE_TASK_TIME_LIMIT_SECONDS: Final = 900
RECONCILE_LEASE_GRACE_SECONDS: Final = 120
RECONCILE_LEASE_SECONDS: Final = RECONCILE_TASK_TIME_LIMIT_SECONDS + RECONCILE_LEASE_GRACE_SECONDS
RECONCILE_QUEUE_CLAIM_TIMEOUT_SECONDS: Final = RECONCILE_LEASE_SECONDS
MAX_GENERATIONS_PER_WORKER: Final = 20

# 健康面板判定阈值: 连续失败达到该值视为不健康。
CONNECTOR_UNHEALTHY_FAILURE_THRESHOLD: Final = 3


def mark_reconcile_dirty(instance_id: int, *, trigger: str) -> bool:
    """推进持久 generation; 返回是否需要新投递一个串行 worker。"""
    now = timezone.now()
    with transaction.atomic():
        instance = (
            ConnectorInstance.objects.select_for_update()
            .filter(id=instance_id)
            .filter(Q(enabled=True) | Q(tombstoned=True))
            .first()
        )
        if instance is None:
            return False
        instance.reconcile_generation += 1
        instance.reconcile_dirty = True
        if (
            trigger == SYNC_TRIGGER_OFFBOARD
            or instance.reconcile_pending_trigger != SYNC_TRIGGER_OFFBOARD
        ):
            instance.reconcile_pending_trigger = trigger
        should_queue = not _reconcile_lease_is_active(instance, now) and (
            not instance.reconcile_worker_queued or _reconcile_queue_is_stale(instance, now)
        )
        if should_queue:
            instance.reconcile_worker_queued = True
            instance.reconcile_worker_queued_at = now
        instance.save(
            update_fields=[
                "reconcile_generation",
                "reconcile_dirty",
                "reconcile_pending_trigger",
                "reconcile_worker_queued",
                "reconcile_worker_queued_at",
                "updated_at",
            ],
        )
    return should_queue


def _reconcile_lease_is_active(instance: ConnectorInstance, now: datetime) -> bool:
    return (
        instance.reconcile_lease_token is not None
        and instance.reconcile_lease_expires_at is not None
        and instance.reconcile_lease_expires_at > now
    )


def _reconcile_queue_is_stale(instance: ConnectorInstance, now: datetime) -> bool:
    return (
        instance.reconcile_worker_queued_at is None
        or instance.reconcile_worker_queued_at
        <= now - timedelta(seconds=RECONCILE_QUEUE_CLAIM_TIMEOUT_SECONDS)
    )


def reconcile_instance(instance_id: int, *, trigger: str | None = None) -> ConnectorSyncRun | None:
    """运行一个数据库租约保护的串行 worker, 并消费期间累积的 dirty generation。"""
    if trigger is not None:
        _ = mark_reconcile_dirty(instance_id, trigger=trigger)
    last_run: ConnectorSyncRun | None = None
    for _ in range(MAX_GENERATIONS_PER_WORKER):
        instance = _claim_generation(instance_id)
        if instance is None:
            break
        started_at = timezone.now()
        report = _reconcile_claimed(instance)
        last_run = record_sync_run(
            instance,
            trigger=instance.reconcile_pending_trigger,
            started_at=started_at,
            report=report,
        )
        if not _finish_generation(instance, report=report):
            break
    return last_run


def _claim_generation(instance_id: int) -> ConnectorInstance | None:
    now = timezone.now()
    with transaction.atomic():
        instance = (
            ConnectorInstance.objects.select_for_update()
            .select_related("app")
            .filter(id=instance_id)
            .filter(Q(enabled=True) | Q(tombstoned=True))
            .first()
        )
        if instance is None:
            return None
        instance.reconcile_worker_queued = False
        instance.reconcile_worker_queued_at = None
        lease_active = (
            instance.reconcile_lease_token is not None
            and instance.reconcile_lease_expires_at is not None
            and instance.reconcile_lease_expires_at > now
        )
        if lease_active or not instance.reconcile_dirty:
            instance.save(
                update_fields=[
                    "reconcile_worker_queued",
                    "reconcile_worker_queued_at",
                    "updated_at",
                ]
            )
            return None
        instance.reconcile_lease_token = uuid.uuid4()
        instance.reconcile_lease_expires_at = now + timedelta(seconds=RECONCILE_LEASE_SECONDS)
        instance.reconcile_dirty = False
        instance.save(
            update_fields=[
                "reconcile_worker_queued",
                "reconcile_worker_queued_at",
                "reconcile_lease_token",
                "reconcile_lease_expires_at",
                "reconcile_dirty",
                "updated_at",
            ],
        )
        return instance


def _reconcile_claimed(instance: ConnectorInstance) -> ReconcileReport:
    connector = get_connector(instance.connector_key)
    if connector is None:
        return ReconcileReport(
            status=SYNC_RUN_STATUS_FAILED,
            error=CONNECTOR_NOT_REGISTERED_TEMPLATE.format(key=instance.connector_key),
        )
    try:
        _bind_external_account(instance, connector)
        desired = build_desired_state(instance)
        return connector.reconcile(instance, desired)
    except ConnectorError as error:
        return ReconcileReport(status=SYNC_RUN_STATUS_FAILED, error=str(error))


def _bind_external_account(instance: ConnectorInstance, connector: BaseConnector) -> None:
    detected = connector.external_account_id(instance.config)
    if not detected:
        return
    if instance.external_account_id:
        if instance.external_account_id != detected:
            raise ConnectorError(EXTERNAL_ACCOUNT_CHANGED_MESSAGE)
        return
    try:
        with transaction.atomic():
            locked = ConnectorInstance.objects.select_for_update().get(id=instance.id)
            if locked.external_account_id and locked.external_account_id != detected:
                raise ConnectorError(EXTERNAL_ACCOUNT_CHANGED_MESSAGE)
            locked.external_account_id = detected
            locked.save(update_fields=["external_account_id", "updated_at"])
    except IntegrityError as error:
        raise ConnectorError(EXTERNAL_ACCOUNT_CONFLICT_MESSAGE) from error
    instance.external_account_id = detected


def claim_instance_lease(instance_id: int) -> ConnectorInstance | None:
    """认领实例租约供快路径写入; 已有活跃租约时不抢占, 返回 None。

    快路径不得清掉 dirty/queued: 若任务中途失败, 待对账请求必须仍在。
    """
    now = timezone.now()
    with transaction.atomic():
        instance = (
            ConnectorInstance.objects.select_for_update()
            .select_related("app")
            .filter(id=instance_id)
            .filter(Q(enabled=True) | Q(tombstoned=True))
            .first()
        )
        if instance is None or _reconcile_lease_is_active(instance, now):
            return None
        instance.reconcile_lease_token = uuid.uuid4()
        instance.reconcile_lease_expires_at = now + timedelta(seconds=RECONCILE_LEASE_SECONDS)
        instance.save(
            update_fields=[
                "reconcile_lease_token",
                "reconcile_lease_expires_at",
                "updated_at",
            ],
        )
        return instance


def release_instance_lease(instance: ConnectorInstance) -> None:
    """释放本任务持有的租约, 让后续对账可以认领; dirty/queued 保持认领时的原值。"""
    with transaction.atomic():
        locked = (
            ConnectorInstance.objects.select_for_update()
            .filter(id=instance.id, reconcile_lease_token=instance.reconcile_lease_token)
            .first()
        )
        if locked is None:
            return
        locked.reconcile_lease_token = None
        locked.reconcile_lease_expires_at = None
        locked.save(
            update_fields=["reconcile_lease_token", "reconcile_lease_expires_at", "updated_at"],
        )


def external_write_allowed(
    instance: ConnectorInstance,
    *,
    user_id: str,
    require_active_user: bool,
    allow_unknown_user: bool = False,
    require_clean_dirty: bool = True,
) -> bool:
    """外部写入前续租并检查 lease_token + generation fencing。

    全量对账要求 dirty=False(新 generation 到达则停止写入)。
    快路径只要求租约 token 仍有效, 不得因待对账 dirty 而拒绝踢线。
    """
    user_exists = UserMirror.objects.filter(authentik_user_id=user_id).exists()
    if not user_exists:
        # 外部存在、本地无镜像的 JIT 用户按定义无授权; 只允许收缩/封禁, 扩权仍拒绝。
        if not allow_unknown_user or require_active_user:
            return False
    elif (
        require_active_user
        and not UserMirror.objects.filter(
            authentik_user_id=user_id,
            status=USER_STATUS_ACTIVE,
        ).exists()
    ):
        return False
    if instance.reconcile_lease_token is None:
        return False
    now = timezone.now()
    renewed_until = now + timedelta(seconds=RECONCILE_LEASE_SECONDS)
    query = Q(
        id=instance.id,
        reconcile_generation=instance.reconcile_generation,
        reconcile_lease_token=instance.reconcile_lease_token,
        reconcile_lease_expires_at__gt=now,
    )
    if require_clean_dirty:
        query &= Q(reconcile_dirty=False)
    updated = ConnectorInstance.objects.filter(query).update(
        reconcile_lease_expires_at=renewed_until,
    )
    if updated:
        instance.reconcile_lease_expires_at = renewed_until
    return updated == 1


def expansion_allowed(instance: ConnectorInstance, *, user_id: str) -> bool:
    """扩权/解封前额外检查人员必须仍 active。"""
    return external_write_allowed(instance, user_id=user_id, require_active_user=True)


def _finish_generation(instance: ConnectorInstance, *, report: ReconcileReport) -> bool:
    """仅当前 token 可释放租约; 返回是否还有 dirty generation 要继续消费。"""
    now = timezone.now()
    with transaction.atomic():
        locked = ConnectorInstance.objects.select_for_update().filter(id=instance.id).first()
        if locked is None or locked.reconcile_lease_token != instance.reconcile_lease_token:
            return False
        if locked.reconcile_lease_expires_at is None or locked.reconcile_lease_expires_at <= now:
            locked.reconcile_dirty = True
            locked.save(update_fields=["reconcile_dirty", "updated_at"])
            return False
        if locked.reconcile_generation != instance.reconcile_generation:
            _release_advanced_generation(locked)
            return True
        return _complete_generation(instance, locked, report=report)


def _release_advanced_generation(instance: ConnectorInstance) -> None:
    instance.reconcile_dirty = True
    instance.reconcile_lease_token = None
    instance.reconcile_lease_expires_at = None
    instance.save(
        update_fields=[
            "reconcile_dirty",
            "reconcile_lease_token",
            "reconcile_lease_expires_at",
            "updated_at",
        ],
    )


def _complete_generation(
    claimed: ConnectorInstance,
    locked: ConnectorInstance,
    *,
    report: ReconcileReport,
) -> bool:
    success = report.status == SYNC_RUN_STATUS_SUCCESS
    if success:
        locked.reconciled_generation = claimed.reconcile_generation
    else:
        locked.reconcile_dirty = True
    locked.reconcile_lease_token = None
    locked.reconcile_lease_expires_at = None
    locked.save(
        update_fields=[
            "reconciled_generation",
            "reconcile_dirty",
            "reconcile_lease_token",
            "reconcile_lease_expires_at",
            "updated_at",
        ],
    )
    if not success:
        return False
    _ = (
        ConnectorMapping.objects.filter(instance=locked)
        .filter(
            Q(tombstoned=True) | Q(authorization_group__isnull=True),
        )
        .delete()
    )
    if locked.tombstoned:
        _ = locked.delete()
        return False
    return locked.reconcile_dirty


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
    if not update_health:
        return run
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
