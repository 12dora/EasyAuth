from __future__ import annotations

import uuid
from dataclasses import dataclass
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
    ExternalGroup,
    ReconcileReport,
)
from easyauth.connectors.models import (
    SYNC_RUN_STATUS_FAILED,
    SYNC_RUN_STATUS_SUCCESS,
    SYNC_TRIGGER_OFFBOARD,
    ConnectorExternalGroup,
    ConnectorInstance,
    ConnectorMapping,
    ConnectorSyncRun,
)
from easyauth.connectors.registry import get_connector
from easyauth.grants.models import GRANT_STATUS_ACTIVE, AccessGrantGroup

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

CONNECTOR_NOT_REGISTERED_TEMPLATE: Final = "连接器类型 {key} 未在 EASYAUTH_CONNECTORS 注册。"
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
EXTERNAL_GROUP_REFRESH_STATUS_RUNNING: Final = "running"
EXTERNAL_GROUP_REFRESH_STATUS_SUCCESS: Final = "success"
EXTERNAL_GROUP_REFRESH_STATUS_FAILED: Final = "failed"
EXTERNAL_GROUP_REFRESH_BULK_BATCH_SIZE: Final = 500


@dataclass(frozen=True, slots=True)
class ExternalGroupRefreshResult:
    active_count: int
    deactivated_count: int
    refreshed_at: datetime


def build_desired_state(instance: ConnectorInstance) -> DesiredState:
    """构建只包含有效成员的投影, 并与权限查询共用 active 组与期限口径。"""
    now = timezone.now()
    mappings = tuple(
        ConnectorMapping.objects.filter(instance=instance).select_related("authorization_group"),
    )
    active_mappings = _active_connector_mappings(mappings)
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
    user_group_refs, profiles = _project_memberships(
        instance,
        membership_rows,
        external_ref_by_group_id,
    )
    return DesiredState(
        user_groups={user_id: frozenset(refs) for user_id, refs in user_group_refs.items()},
        profiles=profiles,
        managed_group_refs=frozenset(mapping.external_ref for mapping in mappings),
        # external_ref 是不可变外部组 ID, 不支持按名称自动创建; 字段保留为空以消除死配置假成功。
        auto_create_group_refs=frozenset(),
    )


def _active_connector_mappings(
    mappings: tuple[ConnectorMapping, ...],
) -> tuple[ConnectorMapping, ...]:
    # 仅 active 且未 tombstone 的映射参与扩权; tombstone/缺组映射仍进入 managed 以便收缩清理。
    return tuple(
        mapping
        for mapping in mappings
        if (
            not mapping.tombstoned
            and mapping.authorization_group is not None
            and mapping.authorization_group.is_active
        )
    )


def _project_memberships(
    instance: ConnectorInstance,
    membership_rows: Iterable[AccessGrantGroup],
    external_ref_by_group_id: dict[int | None, str],
) -> tuple[dict[str, set[str]], dict[str, DesiredUserProfile]]:
    user_group_refs: dict[str, set[str]] = {}
    profiles: dict[str, DesiredUserProfile] = {}
    if instance.tombstoned:
        return user_group_refs, profiles
    for row in membership_rows:
        user = row.grant.user
        refs = user_group_refs.setdefault(user.authentik_user_id, set())
        refs.add(external_ref_by_group_id[row.authorization_group_id])
        profiles[user.authentik_user_id] = DesiredUserProfile(
            user_id=user.authentik_user_id,
            name=user.name,
            email=user.email,
        )
    return user_group_refs, profiles


def refresh_external_groups(instance_id: int) -> ExternalGroupRefreshResult:
    instance = ConnectorInstance.objects.select_related("app").filter(id=instance_id).first()
    if instance is None or instance.tombstoned:
        return ExternalGroupRefreshResult(
            active_count=0,
            deactivated_count=0,
            refreshed_at=timezone.now(),
        )
    connector = get_connector(instance.connector_key)
    if connector is None:
        message = CONNECTOR_NOT_REGISTERED_TEMPLATE.format(key=instance.connector_key)
        _mark_instance_external_group_refresh_failed(instance, message)
        raise ConnectorError(message)
    started_at = timezone.now()
    _start_external_group_refresh(instance)
    try:
        active_count, last_cursor = _consume_external_group_pages(
            instance,
            connector,
            started_at,
        )
    except ConnectorError as error:
        _mark_instance_external_group_refresh_failed(instance, str(error))
        raise
    deactivated_count = _finish_external_group_refresh(
        instance,
        started_at=started_at,
        last_cursor=last_cursor,
    )
    return ExternalGroupRefreshResult(
        active_count=active_count,
        deactivated_count=deactivated_count,
        refreshed_at=started_at,
    )


def _start_external_group_refresh(instance: ConnectorInstance) -> None:
    instance.external_groups_refresh_status = EXTERNAL_GROUP_REFRESH_STATUS_RUNNING
    instance.external_groups_refresh_cursor = ""
    instance.save(
        update_fields=[
            "external_groups_refresh_status",
            "external_groups_refresh_cursor",
            "updated_at",
        ]
    )


def _consume_external_group_pages(
    instance: ConnectorInstance,
    connector: BaseConnector,
    started_at: datetime,
) -> tuple[int, str]:
    active_count = 0
    last_cursor = ""
    for page in connector.iter_external_group_pages(instance.config):
        groups = page.groups
        last_cursor = page.cursor
        active_count += len(groups)
        _upsert_external_group_page(
            instance=instance,
            groups=groups,
            seen_at=started_at,
            cursor=last_cursor,
        )
    return active_count, last_cursor


def _finish_external_group_refresh(
    instance: ConnectorInstance,
    *,
    started_at: datetime,
    last_cursor: str,
) -> int:
    with transaction.atomic():
        deactivated_count = ConnectorExternalGroup.objects.filter(
            instance=instance,
            is_active=True,
            last_seen_at__lt=started_at,
        ).update(is_active=False)
        instance.last_error = ""
        instance.external_groups_refresh_status = EXTERNAL_GROUP_REFRESH_STATUS_SUCCESS
        instance.external_groups_refresh_cursor = last_cursor
        instance.external_groups_refreshed_at = started_at
        instance.save(
            update_fields=[
                "last_error",
                "external_groups_refresh_status",
                "external_groups_refresh_cursor",
                "external_groups_refreshed_at",
                "updated_at",
            ]
        )
    return deactivated_count


def _upsert_external_group_page(
    *,
    instance: ConnectorInstance,
    groups: tuple[ExternalGroup, ...],
    seen_at: datetime,
    cursor: str,
) -> None:
    rows = [
        ConnectorExternalGroup(
            instance=instance,
            external_ref=group.ref,
            external_name=group.name,
            is_active=True,
            last_seen_at=seen_at,
        )
        for group in groups
    ]
    with transaction.atomic():
        if rows:
            _ = ConnectorExternalGroup.objects.bulk_create(
                rows,
                batch_size=EXTERNAL_GROUP_REFRESH_BULK_BATCH_SIZE,
                update_conflicts=True,
                update_fields=["external_name", "is_active", "last_seen_at"],
                unique_fields=["instance", "external_ref"],
            )
        _ = ConnectorInstance.objects.filter(id=instance.id).update(
            external_groups_refresh_cursor=cursor,
            updated_at=timezone.now(),
        )
        instance.external_groups_refresh_cursor = cursor


def _mark_instance_external_group_refresh_failed(
    instance: ConnectorInstance,
    message: str,
) -> None:
    instance.last_error = message
    instance.external_groups_refresh_status = EXTERNAL_GROUP_REFRESH_STATUS_FAILED
    instance.save(update_fields=["last_error", "external_groups_refresh_status", "updated_at"])


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


def external_write_allowed(
    instance: ConnectorInstance,
    *,
    user_id: str,
    require_active_user: bool,
) -> bool:
    """外部写入前续租并检查 lease_token + generation fencing。"""
    if not UserMirror.objects.filter(authentik_user_id=user_id).exists():
        return False
    if (
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
