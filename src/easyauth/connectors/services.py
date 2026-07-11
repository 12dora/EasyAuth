from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.connectors.base import (
    BaseConnector,
    ConnectorError,
    DesiredState,
    DesiredUserProfile,
    ReconcileReport,
)
from easyauth.connectors.models import (
    SYNC_RUN_STATUS_FAILED,
    SYNC_RUN_STATUS_SUCCESS,
    SYNC_TRIGGER_OFFBOARD,
    ConnectorInstance,
    ConnectorMapping,
    ConnectorSyncRun,
)
from easyauth.connectors.registry import get_connector
from easyauth.grants.models import GRANT_STATUS_ACTIVE, AccessGrantGroup

if TYPE_CHECKING:
    from datetime import datetime

CONNECTOR_NOT_REGISTERED_TEMPLATE: Final = "连接器类型 {key} 未在 EASYAUTH_CONNECTORS 注册。"
EXTERNAL_ACCOUNT_CHANGED_MESSAGE: Final = "连接器不可重新绑定到另一个外部账户。"
EXTERNAL_ACCOUNT_CONFLICT_MESSAGE: Final = "该外部账户已绑定到另一个 EasyAuth App。"
RECONCILE_LEASE_SECONDS: Final = 600
RECONCILE_QUEUE_CLAIM_TIMEOUT_SECONDS: Final = 600
MAX_GENERATIONS_PER_WORKER: Final = 20

# 健康面板判定阈值: 连续失败达到该值视为不健康。
CONNECTOR_UNHEALTHY_FAILURE_THRESHOLD: Final = 3


def build_desired_state(instance: ConnectorInstance) -> DesiredState:
    """构建只包含有效成员的投影, 并与权限查询共用 active 组与期限口径。"""
    now = timezone.now()
    mappings = tuple(
        ConnectorMapping.objects.filter(instance=instance).select_related("authorization_group"),
    )
    # 仅 active 且未 tombstone 的映射参与扩权; tombstone/缺组映射仍进入 managed 以便收缩清理。
    active_mappings = tuple(
        mapping
        for mapping in mappings
        if (
            not mapping.tombstoned
            and mapping.authorization_group is not None
            and mapping.authorization_group.is_active
        )
    )
    external_ref_by_group_id = {
        mapping.authorization_group_id: mapping.external_ref for mapping in active_mappings
    }
    membership_rows = (
        AccessGrantGroup.objects.filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now),
            grant__app_id=instance.app_id,
            grant__is_current=True,
            grant__status=GRANT_STATUS_ACTIVE,
            grant__user__status=USER_STATUS_ACTIVE,
            authorization_group_id__in=external_ref_by_group_id,
            authorization_group__is_active=True,
        )
        .select_related("grant__user", "authorization_group")
        .order_by("id")
    )
    user_group_refs: dict[str, set[str]] = {}
    profiles: dict[str, DesiredUserProfile] = {}
    if not instance.tombstoned:
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
        managed_group_refs=frozenset(mapping.external_ref for mapping in mappings),
        # external_ref 是不可变外部组 ID, 不支持按名称自动创建; 字段保留为空以消除死配置假成功。
        auto_create_group_refs=frozenset(),
    )


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
        should_queue = not lease_active and (
            not instance.reconcile_worker_queued or queue_stale
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


def reset_worker_dispatch(instance_id: int) -> None:
    """Broker 投递失败时复位 claim 标记; dirty/generation 保持等待重试。"""
    _ = ConnectorInstance.objects.filter(
        id=instance_id,
        reconcile_lease_token__isnull=True,
    ).update(
        reconcile_worker_queued=False,
        reconcile_worker_queued_at=None,
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


def expansion_allowed(instance: ConnectorInstance, *, user_id: str) -> bool:
    """扩权/解封前续租并检查 generation、dirty 和人员生命周期 fencing。"""
    if not UserMirror.objects.filter(
        authentik_user_id=user_id,
        status=USER_STATUS_ACTIVE,
    ).exists():
        return False
    if instance.reconcile_lease_token is None:
        return False
    now = timezone.now()
    renewed_until = now + timedelta(seconds=RECONCILE_LEASE_SECONDS)
    updated = ConnectorInstance.objects.filter(
        id=instance.id,
        reconcile_generation=instance.reconcile_generation,
        reconcile_dirty=False,
        reconcile_lease_token=instance.reconcile_lease_token,
        reconcile_lease_expires_at__gt=now,
    ).update(reconcile_lease_expires_at=renewed_until)
    if updated:
        instance.reconcile_lease_expires_at = renewed_until
    return updated == 1


def _finish_generation(instance: ConnectorInstance, *, report: ReconcileReport) -> bool:
    """仅当前 token 可释放租约; 返回是否还有 dirty generation 要继续消费。"""
    with transaction.atomic():
        locked = ConnectorInstance.objects.select_for_update().filter(id=instance.id).first()
        if locked is None or locked.reconcile_lease_token != instance.reconcile_lease_token:
            return False
        current_generation = locked.reconcile_generation == instance.reconcile_generation
        if current_generation:
            locked.reconciled_generation = instance.reconcile_generation
        locked.reconcile_lease_token = None
        locked.reconcile_lease_expires_at = None
        locked.save(
            update_fields=[
                "reconciled_generation",
                "reconcile_lease_token",
                "reconcile_lease_expires_at",
                "updated_at",
            ],
        )
        if current_generation and report.status == SYNC_RUN_STATUS_SUCCESS:
            _ = ConnectorMapping.objects.filter(instance=locked).filter(
                Q(tombstoned=True) | Q(authorization_group__isnull=True),
            ).delete()
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
