from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, cast

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import AppScope, AuthorizationGroupGrant
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
from easyauth.grants.models import GRANT_STATUS_ACTIVE, AccessGrantGroup, AccessGrantPermission

if TYPE_CHECKING:
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
    # 2026-09-07 事故: 直接权限覆盖组所需权限时也投影, 不能只看 AccessGrantGroup。
    # (a) 当前授权含该映射组的未过期成员; 或
    # (b) required(G) 非空且包含于用户有效权限(组成员展开与直接授权, 口径同 grants.query)。
    user_group_refs, profiles = _project_users_by_effective_permissions(
        instance,
        active_mappings,
        now,
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


def _project_users_by_effective_permissions(
    instance: ConnectorInstance,
    active_mappings: tuple[ConnectorMapping, ...],
    now: datetime,
) -> tuple[dict[str, set[str]], dict[str, DesiredUserProfile]]:
    user_group_refs: dict[str, set[str]] = {}
    profiles: dict[str, DesiredUserProfile] = {}
    if instance.tombstoned:
        return user_group_refs, profiles
    active_scope_keys = _active_scope_keys(instance.app_id)
    required_by_group_id = _required_permission_pairs_by_group(
        app_id=instance.app_id,
        active_scope_keys=active_scope_keys,
    )
    users_by_id, memberships_by_user, effective_by_user = _user_effective_permission_index(
        instance,
        now=now,
        active_scope_keys=active_scope_keys,
        required_by_group_id=required_by_group_id,
    )
    for mapping in active_mappings:
        group_id = mapping.authorization_group_id
        if group_id is None:
            continue
        required = required_by_group_id.get(group_id, set())
        for user_id, user in users_by_id.items():
            via_membership = group_id in memberships_by_user.get(user_id, set())
            via_coverage = bool(required) and required <= effective_by_user.get(user_id, set())
            if not (via_membership or via_coverage):
                continue
            refs = user_group_refs.setdefault(user_id, set())
            refs.add(mapping.external_ref)
            profiles[user_id] = DesiredUserProfile(
                user_id=user.authentik_user_id,
                name=user.name,
                email=user.email,
            )
    return user_group_refs, profiles


def _active_scope_keys(app_id: int) -> set[str]:
    return set(
        AppScope.objects.filter(app_id=app_id, is_active=True).values_list("key", flat=True),
    )


def _supported_scope_keys(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items = cast("list[object]", value)
    return [scope for scope in items if isinstance(scope, str)]


def _scope_key_is_effective(
    scope_key: str,
    supported_scopes: object,
    active_scope_keys: set[str],
) -> bool:
    return scope_key in active_scope_keys and scope_key in _supported_scope_keys(supported_scopes)


def _required_permission_pairs_by_group(
    *,
    app_id: int,
    active_scope_keys: set[str],
) -> dict[int, set[tuple[str, str]]]:
    links = AuthorizationGroupGrant.objects.select_related("permission").filter(
        authorization_group__app_id=app_id,
        authorization_group__is_active=True,
        is_active=True,
        permission__is_active=True,
        permission__deprecated_at__isnull=True,
    )
    required_by_group_id: dict[int, set[tuple[str, str]]] = {}
    for link in links:
        if not _scope_key_is_effective(
            link.scope_key,
            link.permission.supported_scopes,
            active_scope_keys,
        ):
            continue
        required_by_group_id.setdefault(link.authorization_group_id, set()).add(
            (link.permission.key, link.scope_key),
        )
    return required_by_group_id


def _user_effective_permission_index(
    instance: ConnectorInstance,
    *,
    now: datetime,
    active_scope_keys: set[str],
    required_by_group_id: dict[int, set[tuple[str, str]]],
) -> tuple[dict[str, UserMirror], dict[str, set[int]], dict[str, set[tuple[str, str]]]]:
    users_by_id: dict[str, UserMirror] = {}
    memberships_by_user: dict[str, set[int]] = {}
    effective_by_user: dict[str, set[tuple[str, str]]] = {}
    current_grant = Q(
        grant__app_id=instance.app_id,
        grant__is_current=True,
        grant__status=GRANT_STATUS_ACTIVE,
        grant__user__status=USER_STATUS_ACTIVE,
    )
    membership_rows = (
        AccessGrantGroup.objects.filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now),
            current_grant,
            authorization_group__is_active=True,
        )
        .select_related("grant__user")
        .order_by("id")
    )
    for row in membership_rows:
        user = row.grant.user
        user_id = user.authentik_user_id
        users_by_id[user_id] = user
        memberships_by_user.setdefault(user_id, set()).add(row.authorization_group_id)
        group_pairs = required_by_group_id.get(row.authorization_group_id)
        if group_pairs:
            effective_by_user.setdefault(user_id, set()).update(group_pairs)
    direct_rows = AccessGrantPermission.objects.select_related("permission", "grant__user").filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now),
        current_grant,
        permission__is_active=True,
        permission__deprecated_at__isnull=True,
    )
    for row in direct_rows:
        if not _scope_key_is_effective(
            row.scope_key,
            row.permission.supported_scopes,
            active_scope_keys,
        ):
            continue
        user = row.grant.user
        user_id = user.authentik_user_id
        users_by_id[user_id] = user
        effective_by_user.setdefault(user_id, set()).add((row.permission.key, row.scope_key))
    return users_by_id, memberships_by_user, effective_by_user


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
