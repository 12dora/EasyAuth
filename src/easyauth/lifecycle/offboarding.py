from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final, cast

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import UserMirror
from easyauth.applications.handover_capability import _seed_asset_type_placeholders
from easyauth.applications.models import (
    HANDOVER_CAPABILITY_DECLARED,
    HANDOVER_CAPABILITY_NONE,
    App,
    AppScope,
)
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission
from easyauth.lifecycle.assignee import AssigneeResolution, apply_assignee, resolve_assignee
from easyauth.lifecycle.core import (
    LIFECYCLE_ACTOR_ID,
    TASK_KIND_CONFLICT_MESSAGE,
    record_task_event,
    refresh_task_status,
)
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover import initial_action_status_for_app
from easyauth.lifecycle.models import (
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_PENDING,
    ACTION_STATUS_SKIPPED,
    HANDOVER_ESCALATION_DAYS,
    HANDOVER_KIND_OFFBOARD,
    HANDOVER_KIND_PRE_OFFBOARD,
    HANDOVER_KIND_REASSIGN,
    HANDOVER_KIND_TRANSFER,
    TASK_OPEN_STATUSES,
    HandoverAppAction,
    HandoverGrantItem,
    HandoverTask,
    HandoverTeamItem,
    TransferPlan,
)
from easyauth.lifecycle.tasks import DISABLE_ACCOUNT_TASK_NAME
from easyauth.outbox.services import enqueue_task
from easyauth.teams.models import TEAM_MEMBER_ROLE_LEADER, TeamMember


@dataclass(frozen=True, slots=True)
class OffboardingStartResult:
    task: HandoverTask
    created: bool
    removed_membership_count: int

LOCAL_ADMIN_LIFECYCLE_MESSAGE: Final = "系统内置管理员不参与离职/转岗交接。"

def _assert_lifecycle_subject(subject: UserMirror) -> None:
    # break-glass 本地管理员不是员工, 禁止对其建离职/转岗交接单(误操作会禁掉救援入口)。
    if subject.authentik_user_id.startswith(LOCAL_ADMIN_SUBJECT_PREFIX):
        raise HandoverConflictError(LOCAL_ADMIN_LIFECYCLE_MESSAGE)


def ensure_handover_task(
    *,
    subject: UserMirror,
    kind: str,
    created_by: str,
    reason: str = "",
    snapshot_grant_ids: tuple[int, ...] | None = None,
    app_keys: tuple[str, ...] | None = None,
    authority_source: str = "",
    creation_idempotency_key: str = "",
    creation_payload_sha256: str = "",
    assignee_resolution: AssigneeResolution | None = None,
    raise_on_existing: bool = False,
) -> tuple[HandoverTask, bool]:
    """建单(幂等): 同一当事人已有进行中交接单时直接返回既有单。

    offboard 遇到 open pre_offboard → 升级(00 §8.3 / 01 §5.1.2)。
    ``raise_on_existing=True`` 时同 kind open 单抛 open_task_exists(门户自助)。
    """
    _assert_lifecycle_subject(subject)
    idempotency = _CreationIdempotency(
        key=creation_idempotency_key,
        payload_sha256=creation_payload_sha256,
    )
    subject_pk = cast("int", subject.pk)
    with transaction.atomic():
        subject = UserMirror.objects.select_for_update().get(pk=subject_pk)

        # 幂等键命中: 同 initiator + key
        existing_by_key = _task_by_idempotency_key(created_by=created_by, idempotency=idempotency)
        if existing_by_key is not None:
            return existing_by_key, False

        existing = _open_lifecycle_task(subject, kind=kind)
        if existing is not None:
            return _reuse_or_upgrade_existing(
                existing,
                kind=kind,
                created_by=created_by,
                reason=reason,
                snapshot_grant_ids=snapshot_grant_ids,
                raise_on_existing=raise_on_existing,
            ), False

        self_service = _is_subject_self_pre_offboard(subject, kind=kind, created_by=created_by)
        resolved_authority = _resolved_authority_source(
            authority_source=authority_source,
            self_service=self_service,
        )

        snapshot_grants = _snapshot_grants(
            subject=subject,
            explicit_grant_ids=snapshot_grant_ids,
        )
        task, won_create = _create_task_with_idempotency_constraint(
            kind=kind,
            subject=subject,
            created_by=created_by,
            reason=reason,
            authority_source=resolved_authority,
            creation_idempotency_key=idempotency.key,
            creation_payload_sha256=idempotency.payload_sha256,
        )
        if not won_create:
            return task, False
        _assign_initial_assignee(
            task,
            subject=subject,
            created_by=created_by,
            assignee_resolution=assignee_resolution,
            self_service=self_service,
        )
        _snapshot_grant_items(task, grants=snapshot_grants)
        _snapshot_app_actions(task, grants=snapshot_grants, app_keys=app_keys)
        _snapshot_leader_teams(task)
        if kind == HANDOVER_KIND_TRANSFER:
            _ = TransferPlan.objects.create(task=task)
        if kind == HANDOVER_KIND_OFFBOARD:
            from easyauth.lifecycle.approvals import reassign_approvals_for_departed

            reassign_approvals_for_departed(
                subject=subject,
                task=task,
                actor_id=created_by,
            )
        _record_task_creation_events(
            task,
            kind=kind,
            created_by=created_by,
            resolved_authority=resolved_authority,
            app_keys=app_keys,
        )
        return refresh_task_status(task), True


@dataclass(frozen=True, slots=True)
class _CreationIdempotency:
    """建单幂等键与冻结 body 摘要; 同 key 不同摘要一律 409。"""

    key: str
    payload_sha256: str


def _task_by_idempotency_key(
    *,
    created_by: str,
    idempotency: _CreationIdempotency,
) -> HandoverTask | None:
    if not idempotency.key:
        return None
    existing_by_key = (
        HandoverTask.objects.select_for_update()
        .filter(
            created_by=created_by,
            creation_idempotency_key=idempotency.key,
        )
        .first()
    )
    if existing_by_key is None:
        return None
    if existing_by_key.creation_payload_sha256 != idempotency.payload_sha256:
        raise HandoverConflictError("idempotency_conflict")
    return existing_by_key


def _open_lifecycle_task(subject: UserMirror, *, kind: str) -> HandoverTask | None:
    # reassign 可与其他 open 单并存; 生命周期类单据一人一张。
    if kind == HANDOVER_KIND_REASSIGN:
        return None
    return (
        HandoverTask.objects.select_for_update()
        .filter(
            subject_user=subject,
            status__in=TASK_OPEN_STATUSES,
            kind__in=(
                HANDOVER_KIND_OFFBOARD,
                HANDOVER_KIND_TRANSFER,
                HANDOVER_KIND_PRE_OFFBOARD,
            ),
        )
        .first()
    )


def _reuse_or_upgrade_existing(
    existing: HandoverTask,
    *,
    kind: str,
    created_by: str,
    reason: str,
    snapshot_grant_ids: tuple[int, ...] | None,
    raise_on_existing: bool,
) -> HandoverTask:
    # pre_offboard → offboard 升级是唯一允许的 kind 变更
    if existing.kind == HANDOVER_KIND_PRE_OFFBOARD and kind == HANDOVER_KIND_OFFBOARD:
        return upgrade_pre_offboard_to_offboard(
            existing,
            created_by=created_by,
            reason=reason or "目录同步检出离职",
            snapshot_grant_ids=snapshot_grant_ids,
        )
    if existing.kind != kind:
        raise HandoverConflictError(TASK_KIND_CONFLICT_MESSAGE)
    # 同 kind open 单: 内部/系统调用可幂等返回; 门户自助建单要求 409 open_task_exists
    # (01 §6.1), 由 raise_on_existing 区分。
    if raise_on_existing:
        raise HandoverConflictError("open_task_exists")
    return existing


def _is_subject_self_pre_offboard(subject: UserMirror, *, kind: str, created_by: str) -> bool:
    return kind == HANDOVER_KIND_PRE_OFFBOARD and created_by == subject.authentik_user_id


def _resolved_authority_source(*, authority_source: str, self_service: bool) -> str:
    from easyauth.lifecycle.models import (
        AUTHORITY_SOURCE_MANAGER_CHAIN,
        AUTHORITY_SOURCE_SUBJECT,
    )

    if authority_source:
        return authority_source
    return AUTHORITY_SOURCE_SUBJECT if self_service else AUTHORITY_SOURCE_MANAGER_CHAIN


def _assign_initial_assignee(
    task: HandoverTask,
    *,
    subject: UserMirror,
    created_by: str,
    assignee_resolution: AssigneeResolution | None,
    self_service: bool,
) -> None:
    if not self_service:
        resolution = assignee_resolution or resolve_assignee(subject)
        _ = apply_assignee(
            task,
            resolution,
            actor_id=created_by,
            reason="task_created",
        )
        return

    from easyauth.lifecycle.models import ASSIGNEE_STATE_SUBJECT

    # 自助 pre_offboard 不走 resolve_assignee, 避免伪造 degraded 审计。
    task.assignee = subject
    task.assignee_state = ASSIGNEE_STATE_SUBJECT
    task.escalation_level = 0
    task.escalation_deadline = timezone.now() + timedelta(
        days=HANDOVER_ESCALATION_DAYS,
    )
    task.save(
        update_fields=[
            "assignee",
            "assignee_state",
            "escalation_level",
            "escalation_deadline",
            "updated_at",
        ],
    )
    record_task_event(
        task,
        action="handover_assignee_assigned",
        actor_id=created_by,
        actor_type="user",
        extra={"assignee_state": ASSIGNEE_STATE_SUBJECT},
    )


def _record_task_creation_events(
    task: HandoverTask,
    *,
    kind: str,
    created_by: str,
    resolved_authority: str,
    app_keys: tuple[str, ...] | None,
) -> None:
    from easyauth.lifecycle.models import (
        AUTHORITY_SOURCE_MANAGER_CHAIN,
        AUTHORITY_SOURCE_SUBJECT,
        AUTHORITY_SOURCE_SUPERUSER,
    )

    record_task_event(
        task,
        action="handover_task_created",
        actor_id=created_by,
        actor_type=(
            "user"
            if resolved_authority in {AUTHORITY_SOURCE_SUBJECT, AUTHORITY_SOURCE_MANAGER_CHAIN}
            and created_by not in {"directory_sync", LIFECYCLE_ACTOR_ID}
            else None
        ),
    )
    if kind == HANDOVER_KIND_REASSIGN:
        record_task_event(
            task,
            action="handover_reassign_created",
            actor_id=created_by,
            actor_type=(
                "admin" if resolved_authority == AUTHORITY_SOURCE_SUPERUSER else "user"
            ),
            extra={"app_keys": list(app_keys or ())},
        )


def _create_task_with_idempotency_constraint(
    *,
    kind: str,
    subject: UserMirror,
    created_by: str,
    reason: str,
    authority_source: str,
    creation_idempotency_key: str,
    creation_payload_sha256: str,
) -> tuple[HandoverTask, bool]:
    try:
        # savepoint 让唯一键竞态只回滚 INSERT，本事务仍可读取赢家并按冻结 body 判定。
        with transaction.atomic():
            task = HandoverTask.objects.create(
                kind=kind,
                subject_user=subject,
                created_by=created_by,
                reason=reason,
                generation=1,
                authority_source=authority_source,
                creation_idempotency_key=creation_idempotency_key,
                creation_payload_sha256=creation_payload_sha256,
            )
        return task, True
    except IntegrityError:
        if not creation_idempotency_key:
            raise
        existing_by_key = (
            HandoverTask.objects.select_for_update()
            .filter(
                created_by=created_by,
                creation_idempotency_key=creation_idempotency_key,
            )
            .first()
        )
        if existing_by_key is None:
            raise
        if existing_by_key.creation_payload_sha256 != creation_payload_sha256:
            raise HandoverConflictError("idempotency_conflict")
        return existing_by_key, False


def upgrade_pre_offboard_to_offboard(
    task: HandoverTask,
    *,
    created_by: str,
    reason: str = "",
    snapshot_grant_ids: tuple[int, ...] | None = None,
) -> HandoverTask:
    """00 §8.3 / 01 §5.1.2: pre_offboard → offboard 升级。调用方须已锁 task。"""
    from easyauth.lifecycle.handover import reset_action_for_upgrade
    from easyauth.lifecycle.lease import has_active_lease
    from easyauth.lifecycle.approvals import reassign_approvals_for_departed

    if task.kind != HANDOVER_KIND_PRE_OFFBOARD:
        raise HandoverConflictError(TASK_KIND_CONFLICT_MESSAGE)
    if task.status not in TASK_OPEN_STATUSES:
        raise HandoverConflictError(TASK_KIND_CONFLICT_MESSAGE)

    # 任何 action 有未释放租约 → 409
    actions = list(HandoverAppAction.objects.select_for_update().filter(task=task))
    for action in actions:
        if has_active_lease(
            subject_user_id=int(task.subject_user_id),  # type: ignore[arg-type]
            app_id=int(action.app_id),  # type: ignore[arg-type]
        ):
            from easyauth.lifecycle.lease import HANDOVER_EXECUTION_IN_FLIGHT

            raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)

    old_kind = task.kind
    task.kind = HANDOVER_KIND_OFFBOARD
    task.generation += 1
    if reason:
        task.reason = reason
    task.save(update_fields=["kind", "generation", "reason", "updated_at"])

    # assignee 从本人重解析为主管
    resolution = resolve_assignee(task.subject_user)
    _ = apply_assignee(
        task,
        resolution,
        actor_id=created_by,
        reason="pre_offboard_upgraded",
    )

    for action in actions:
        _ = reset_action_for_upgrade(action, task=task)

    # 重新快照授权 + 重新盘点 APP action / 主管团队(00 §8.3 / D7)
    snapshot_grants = _snapshot_grants(
        subject=task.subject_user,
        explicit_grant_ids=snapshot_grant_ids,
    )
    _snapshot_grant_items(task, grants=snapshot_grants)
    _snapshot_app_actions(task, grants=snapshot_grants, app_keys=None)
    _snapshot_leader_teams(task)

    reassign_approvals_for_departed(
        subject=task.subject_user,
        task=task,
        actor_id=created_by,
    )
    record_task_event(
        task,
        action="handover_task_upgraded",
        actor_id=created_by,
        extra={"old_kind": old_kind, "generation": task.generation},
    )
    return refresh_task_status(task)


def start_offboarding(
    subject: UserMirror,
    *,
    created_by: str = "directory_sync",
    snapshot_grant_ids: tuple[int, ...] | None = None,
) -> OffboardingStartResult:
    """离职立即项(§2.2 铁律一): 建单 + 禁号入列 + 移出所有团队; 数据交接进入缓冲。

    调用方须保证授权撤销已由既有离职回收完成(apply_directory_status)。
    open pre_offboard → 升级(ensure_handover_task 内)。
    """
    with transaction.atomic():
        task, created = ensure_handover_task(
            subject=subject,
            kind=HANDOVER_KIND_OFFBOARD,
            created_by=created_by,
            reason="目录同步检出离职" if created_by == "directory_sync" else "",
            snapshot_grant_ids=snapshot_grant_ids,
        )
        removed = _remove_team_memberships(subject, task)
        _schedule_account_disable(subject, task=task)
    return OffboardingStartResult(
        task=task,
        created=created,
        removed_membership_count=removed,
    )


def _snapshot_grant_items(task: HandoverTask, *, grants: list[AccessGrant]) -> None:
    now = timezone.now()
    for grant in grants:
        group_links = (
            AccessGrantGroup.objects.select_related("authorization_group")
            .filter(grant=grant, authorization_group__is_active=True)
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        )
        for link in group_links:
            _ = HandoverGrantItem.objects.create(
                task=task,
                app=grant.app,
                generation=task.generation,
                app_key_snapshot=grant.app.app_key,
                app_name_snapshot=grant.app.name,
                app_catalog_version_snapshot=grant.app.catalog_version,
                authorization_group=link.authorization_group,
                target_kind_snapshot="group",
                target_key_snapshot=link.authorization_group.key,
                target_name_snapshot=link.authorization_group.name,
                source_grant_id=grant.id,
                source_grant_version=grant.version,
                grant_type="permanent" if link.expires_at is None else "timed",
                grant_expires_at=link.expires_at,
            )
        permission_links = (
            AccessGrantPermission.objects.select_related("permission")
            .filter(
                grant=grant,
                permission__is_active=True,
                permission__deprecated_at__isnull=True,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        )
        active_scopes = set(
            AppScope.objects.filter(app=grant.app, is_active=True).values_list("key", flat=True),
        )
        for permission_link in permission_links:
            if permission_link.scope_key not in active_scopes:
                continue
            _ = HandoverGrantItem.objects.create(
                task=task,
                app=grant.app,
                generation=task.generation,
                app_key_snapshot=grant.app.app_key,
                app_name_snapshot=grant.app.name,
                app_catalog_version_snapshot=grant.app.catalog_version,
                permission=permission_link.permission,
                scope_key=permission_link.scope_key,
                target_kind_snapshot="permission",
                target_key_snapshot=permission_link.permission.key,
                target_name_snapshot=permission_link.permission.name,
                source_grant_id=grant.id,
                source_grant_version=grant.version,
                grant_type="permanent" if permission_link.expires_at is None else "timed",
                grant_expires_at=permission_link.expires_at,
            )


def _snapshot_app_actions(
    task: HandoverTask,
    *,
    grants: list[AccessGrant],
    app_keys: tuple[str, ...] | None = None,
) -> None:
    # 交接面 = 当事人有授权痕迹的 APP + 已声明交接能力的 APP; reassign 仅限 app_keys。
    # 升级路径复用: get_or_create, 新发现的 APP 才初始化状态。
    if app_keys is not None:
        apps = list(App.objects.filter(app_key__in=app_keys, is_active=True))
    else:
        # 交接面 = 有授权痕迹的 APP + 已声明 capability 的 APP。
        # 有授权但 undeclared → blocked(不再静默成功)。
        app_ids = {grant.app_id for grant in grants}
        capability_app_ids = set(
            App.objects.filter(
                is_active=True,
                handover_capability__in=(
                    HANDOVER_CAPABILITY_DECLARED,
                    HANDOVER_CAPABILITY_NONE,
                ),
            ).values_list("id", flat=True),
        )
        apps = list(App.objects.filter(id__in=app_ids | capability_app_ids, is_active=True))
    for app in apps:
        status, blocked_reason, skip_reason, skipped_by = initial_action_status_for_app(app)
        action, created = HandoverAppAction.objects.get_or_create(
            task=task,
            app=app,
            defaults={
                "app_key_snapshot": app.app_key,
                "app_name_snapshot": app.name,
                "app_catalog_version_snapshot": app.catalog_version,
                "generation": task.generation,
                "status": status,
                "blocked_reason": blocked_reason,
                "skip_reason": skip_reason,
                "skipped_by": skipped_by,
                "skipped_at": timezone.now() if status == ACTION_STATUS_SKIPPED else None,
            },
        )
        if not created:
            continue
        if status == ACTION_STATUS_BLOCKED:
            record_task_event(
                task,
                action="handover_action_blocked",
                actor_id=LIFECYCLE_ACTOR_ID,
                actor_type="system",
                extra={"app_key": app.app_key, "blocked_reason": blocked_reason},
            )
        if status == ACTION_STATUS_PENDING:
            _seed_asset_type_placeholders(action)


def _snapshot_grants(
    *,
    subject: UserMirror,
    explicit_grant_ids: tuple[int, ...] | None,
) -> list[AccessGrant]:
    queryset = AccessGrant.objects.select_related("app").filter(
        user=subject,
        app__is_active=True,
    )
    if explicit_grant_ids is not None:
        grants_by_id = {grant.id: grant for grant in queryset.filter(id__in=explicit_grant_ids)}
        missing = set(explicit_grant_ids) - grants_by_id.keys()
        if missing:
            message = f"授权快照不存在: {min(missing)}。"
            raise HandoverError(message)
        return [grants_by_id[grant_id] for grant_id in explicit_grant_ids]
    now = timezone.now()
    return list(
        queryset.filter(is_current=True, status="active")
        .filter(
            Q(grant_groups__expires_at__isnull=True)
            | Q(grant_groups__expires_at__gt=now)
            | Q(grant_permissions__expires_at__isnull=True)
            | Q(grant_permissions__expires_at__gt=now),
        )
        .distinct(),
    )


def _snapshot_leader_teams(task: HandoverTask) -> None:
    led_teams = TeamMember.objects.select_related("team").filter(
        user=task.subject_user,
        role=TEAM_MEMBER_ROLE_LEADER,
        team__is_active=True,
    )
    for membership in led_teams:
        _ = HandoverTeamItem.objects.get_or_create(task=task, team=membership.team)


def _remove_team_memberships(subject: UserMirror, task: HandoverTask) -> int:
    removed, _detail = TeamMember.objects.filter(user=subject).delete()
    if removed:
        record_task_event(
            task,
            action="handover_memberships_removed",
            actor_id=LIFECYCLE_ACTOR_ID,
            extra={"removed_count": removed},
        )
    return removed


def _schedule_account_disable(subject: UserMirror, *, task: HandoverTask) -> None:
    # Authentik 禁号/吊销会话走 Celery(可重试), 不阻塞目录同步事务。
    user_pk = cast("int", subject.pk)
    _ = enqueue_task(
        event_key=f"lifecycle-disable-account:{task.id}",
        task_name=DISABLE_ACCOUNT_TASK_NAME,
        args=[user_pk],
    )
