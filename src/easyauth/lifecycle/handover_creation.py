"""交接单建单、幂等与 pre_offboard 升级。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, cast

from django.db import IntegrityError, transaction
from django.utils import timezone

from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import UserMirror
from easyauth.lifecycle import offboarding_snapshot as _snapshot
from easyauth.lifecycle.approvals import reassign_approvals_for_departed
from easyauth.lifecycle.assignee import (
    AssigneeApplyOptions,
    apply_assignee,
    resolve_assignee,
)
from easyauth.lifecycle.core import (
    LIFECYCLE_ACTOR_ID,
    TASK_KIND_CONFLICT_MESSAGE,
    record_task_event,
    refresh_task_status,
)
from easyauth.lifecycle.errors import HandoverConflictError
from easyauth.lifecycle.handover_actions import reset_action_for_upgrade
from easyauth.lifecycle.lease import HANDOVER_EXECUTION_IN_FLIGHT, has_active_lease
from easyauth.lifecycle.models import (
    ASSIGNEE_STATE_SUBJECT,
    AUTHORITY_SOURCE_MANAGER_CHAIN,
    AUTHORITY_SOURCE_SUBJECT,
    AUTHORITY_SOURCE_SUPERUSER,
    HANDOVER_ESCALATION_DAYS,
    HANDOVER_KIND_OFFBOARD,
    HANDOVER_KIND_PRE_OFFBOARD,
    HANDOVER_KIND_REASSIGN,
    HANDOVER_KIND_TRANSFER,
    TASK_OPEN_STATUSES,
    HandoverAppAction,
    HandoverTask,
    TransferPlan,
)

if TYPE_CHECKING:
    from easyauth.grants.models import AccessGrant
    from easyauth.lifecycle.assignee import AssigneeResolution


@dataclass(frozen=True, slots=True)
class HandoverCreationSpec:
    """建单幂等键与冻结 body 摘要; 同 key 不同摘要一律 409。"""

    reason: str = ""
    snapshot_grant_ids: tuple[int, ...] | None = None
    app_keys: tuple[str, ...] | None = None
    authority_source: str = ""
    creation_idempotency_key: str = ""
    creation_payload_sha256: str = ""
    assignee_resolution: AssigneeResolution | None = None
    raise_on_existing: bool = False


_DEFAULT_HANDOVER_CREATION_SPEC: Final = HandoverCreationSpec()
_IDEMPOTENCY_CONFLICT_MESSAGE: Final = "idempotency_conflict"
_OPEN_TASK_EXISTS_MESSAGE: Final = "open_task_exists"

LOCAL_ADMIN_LIFECYCLE_MESSAGE: Final = "系统内置管理员不参与离职/转岗交接。"


@dataclass(frozen=True, slots=True)
class _CreationContext:
    subject: UserMirror
    reused_task: HandoverTask | None


@dataclass(frozen=True, slots=True)
class _CreationPolicy:
    self_service: bool
    resolved_authority: str
    snapshot_grants: list[AccessGrant]


def _assert_lifecycle_subject(subject: UserMirror) -> None:
    # break-glass 本地管理员不是员工, 禁止对其建离职/转岗交接单(误操作会禁掉救援入口)。
    if subject.authentik_user_id.startswith(LOCAL_ADMIN_SUBJECT_PREFIX):
        raise HandoverConflictError(LOCAL_ADMIN_LIFECYCLE_MESSAGE)


def ensure_handover_task(
    *,
    subject: UserMirror,
    kind: str,
    created_by: str,
    spec: HandoverCreationSpec = _DEFAULT_HANDOVER_CREATION_SPEC,
) -> tuple[HandoverTask, bool]:
    """建单(幂等): 同一当事人已有进行中交接单时直接返回既有单。

    offboard 遇到 open pre_offboard → 升级(00 §8.3 / 01 §5.1.2)。
    ``spec.raise_on_existing=True`` 时同 kind open 单抛 open_task_exists(门户自助)。
    """
    _assert_lifecycle_subject(subject)
    with transaction.atomic():
        context = _lock_creation_context(
            subject=subject,
            kind=kind,
            created_by=created_by,
            spec=spec,
        )
        if context.reused_task is not None:
            return context.reused_task, False
        policy = _resolve_creation_policy(
            subject=context.subject,
            kind=kind,
            created_by=created_by,
            spec=spec,
        )
        task, created = _create_task_and_seed(
            kind=kind,
            created_by=created_by,
            spec=spec,
            context=context,
            policy=policy,
        )
        if not created:
            return task, False
        refreshed = _record_creation_events_and_refresh(
            task,
            kind=kind,
            created_by=created_by,
            spec=spec,
            policy=policy,
        )
        return refreshed, True


def _lock_creation_context(
    *,
    subject: UserMirror,
    kind: str,
    created_by: str,
    spec: HandoverCreationSpec,
) -> _CreationContext:
    locked = UserMirror.objects.select_for_update().get(pk=cast("int", subject.pk))
    existing_by_key = _task_by_idempotency_key(created_by=created_by, spec=spec)
    if existing_by_key is not None:
        return _CreationContext(subject=locked, reused_task=existing_by_key)
    existing = _open_lifecycle_task(locked, kind=kind)
    if existing is not None:
        return _CreationContext(
            subject=locked,
            reused_task=_reuse_or_upgrade_existing(
                existing,
                kind=kind,
                created_by=created_by,
                spec=spec,
            ),
        )
    return _CreationContext(subject=locked, reused_task=None)


def _resolve_creation_policy(
    *,
    subject: UserMirror,
    kind: str,
    created_by: str,
    spec: HandoverCreationSpec,
) -> _CreationPolicy:
    self_service = _is_subject_self_pre_offboard(subject, kind=kind, created_by=created_by)
    resolved_authority = _resolved_authority_source(
        authority_source=spec.authority_source,
        self_service=self_service,
    )
    grants = _snapshot.snapshot_grants(
        subject=subject,
        explicit_grant_ids=spec.snapshot_grant_ids,
    )
    if spec.app_keys is not None:
        # 建单前校验: 未知/停用 key 不得静默丢掉, 否则 reassign 会缺 action。
        _ = _snapshot.resolve_requested_apps(spec.app_keys)
    return _CreationPolicy(
        self_service=self_service,
        resolved_authority=resolved_authority,
        snapshot_grants=grants,
    )


def _create_task_and_seed(
    *,
    kind: str,
    created_by: str,
    spec: HandoverCreationSpec,
    context: _CreationContext,
    policy: _CreationPolicy,
) -> tuple[HandoverTask, bool]:
    task, won_create = _create_task_with_idempotency_constraint(
        kind=kind,
        subject=context.subject,
        created_by=created_by,
        spec=spec,
        resolved_authority=policy.resolved_authority,
    )
    if not won_create:
        return task, False
    _assign_initial_assignee(
        task,
        subject=context.subject,
        created_by=created_by,
        assignee_resolution=spec.assignee_resolution,
        self_service=policy.self_service,
    )
    _snapshot.snapshot_grant_items(task, grants=policy.snapshot_grants)
    _snapshot.snapshot_app_actions(task, grants=policy.snapshot_grants, app_keys=spec.app_keys)
    _snapshot.snapshot_leader_teams(task)
    if kind == HANDOVER_KIND_TRANSFER:
        _ = TransferPlan.objects.create(task=task)
    if kind == HANDOVER_KIND_OFFBOARD:
        reassign_approvals_for_departed(
            subject=context.subject,
            task=task,
            actor_id=created_by,
        )
    return task, True


def _record_creation_events_and_refresh(
    task: HandoverTask,
    *,
    kind: str,
    created_by: str,
    spec: HandoverCreationSpec,
    policy: _CreationPolicy,
) -> HandoverTask:
    _record_task_creation_events(
        task,
        kind=kind,
        created_by=created_by,
        resolved_authority=policy.resolved_authority,
        app_keys=spec.app_keys,
    )
    return refresh_task_status(task)


def _task_by_idempotency_key(
    *,
    created_by: str,
    spec: HandoverCreationSpec,
) -> HandoverTask | None:
    if not spec.creation_idempotency_key:
        return None
    existing_by_key = (
        HandoverTask.objects.select_for_update()
        .filter(
            created_by=created_by,
            creation_idempotency_key=spec.creation_idempotency_key,
        )
        .first()
    )
    if existing_by_key is None:
        return None
    if existing_by_key.creation_payload_sha256 != spec.creation_payload_sha256:
        raise HandoverConflictError(_IDEMPOTENCY_CONFLICT_MESSAGE)
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
    spec: HandoverCreationSpec,
) -> HandoverTask:
    # pre_offboard → offboard 升级是唯一允许的 kind 变更
    if existing.kind == HANDOVER_KIND_PRE_OFFBOARD and kind == HANDOVER_KIND_OFFBOARD:
        return upgrade_pre_offboard_to_offboard(
            existing,
            created_by=created_by,
            reason=spec.reason or "目录同步检出离职",
            snapshot_grant_ids=spec.snapshot_grant_ids,
        )
    if existing.kind != kind:
        raise HandoverConflictError(TASK_KIND_CONFLICT_MESSAGE)
    # 同 kind open 单: 内部/系统调用可幂等返回; 门户自助建单要求 409 open_task_exists
    # (01 §6.1), 由 raise_on_existing 区分。
    if spec.raise_on_existing:
        raise HandoverConflictError(_OPEN_TASK_EXISTS_MESSAGE)
    return existing


def _is_subject_self_pre_offboard(subject: UserMirror, *, kind: str, created_by: str) -> bool:
    return kind == HANDOVER_KIND_PRE_OFFBOARD and created_by == subject.authentik_user_id


def _resolved_authority_source(*, authority_source: str, self_service: bool) -> str:
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
            options=AssigneeApplyOptions(reason="task_created"),
        )
        return

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
            actor_type=("admin" if resolved_authority == AUTHORITY_SOURCE_SUPERUSER else "user"),
            extra={"app_keys": list(app_keys or ())},
        )


def _create_task_with_idempotency_constraint(
    *,
    kind: str,
    subject: UserMirror,
    created_by: str,
    spec: HandoverCreationSpec,
    resolved_authority: str,
) -> tuple[HandoverTask, bool]:
    try:
        # savepoint 让唯一键竞态只回滚 INSERT, 本事务仍可读取赢家并按冻结 body 判定。
        with transaction.atomic():
            task = HandoverTask.objects.create(
                kind=kind,
                subject_user=subject,
                created_by=created_by,
                reason=spec.reason,
                generation=1,
                # 解析完成后刻意不再使用 spec.authority_source, 避免绕过自助建单来源解析。
                authority_source=resolved_authority,
                creation_idempotency_key=spec.creation_idempotency_key,
                creation_payload_sha256=spec.creation_payload_sha256,
            )
    except IntegrityError as exc:
        if not spec.creation_idempotency_key:
            raise
        existing_by_key = (
            HandoverTask.objects.select_for_update()
            .filter(
                created_by=created_by,
                creation_idempotency_key=spec.creation_idempotency_key,
            )
            .first()
        )
        if existing_by_key is None:
            raise
        if existing_by_key.creation_payload_sha256 != spec.creation_payload_sha256:
            raise HandoverConflictError(_IDEMPOTENCY_CONFLICT_MESSAGE) from exc
        return existing_by_key, False
    else:
        return task, True


def upgrade_pre_offboard_to_offboard(
    task: HandoverTask,
    *,
    created_by: str,
    reason: str = "",
    snapshot_grant_ids: tuple[int, ...] | None = None,
) -> HandoverTask:
    """00 §8.3 / 01 §5.1.2: pre_offboard → offboard 升级。调用方须已锁 task。"""
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
        options=AssigneeApplyOptions(reason="pre_offboard_upgraded"),
    )

    for action in actions:
        _ = reset_action_for_upgrade(action, task=task)

    # 重新快照授权 + 重新盘点 APP action / 主管团队(00 §8.3 / D7)
    grants = _snapshot.snapshot_grants(
        subject=task.subject_user,
        explicit_grant_ids=snapshot_grant_ids,
    )
    _snapshot.snapshot_grant_items(task, grants=grants)
    _snapshot.snapshot_app_actions(task, grants=grants, app_keys=None)
    _snapshot.snapshot_leader_teams(task)

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
