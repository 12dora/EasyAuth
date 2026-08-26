"""交接动作、任务与团队条目的状态变更。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from django.db import transaction
from django.utils import timezone

from easyauth.applications.models import (
    HANDOVER_CAPABILITY_DECLARED,
    HANDOVER_CAPABILITY_NONE,
    App,
)
from easyauth.lifecycle.core import (
    ACTION_NOT_OPERABLE_MESSAGE,
    ACTION_SELF_RECEIVER_MESSAGE,
    TASK_NOT_DELETABLE_MESSAGE,
    ensure_action_status,
    ensure_task_open,
    record_task_event,
    refresh_task_status_locked,
)
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover_payloads import (
    ensure_batch_plan_on_413,
)
from easyauth.lifecycle.handover_shared import (
    DECLARED_WITHOUT_URL_MESSAGE,
    POLICY_REMOVED_MESSAGE,
    SKIP_REASON_CAPABILITY_NONE,
    handover_hook_url,
    locked_action,
)
from easyauth.lifecycle.lease import (
    HANDOVER_EXECUTION_IN_FLIGHT,
    action_execution_in_flight,
    assignment_mutation_in_flight,
    has_active_lease,
)
from easyauth.lifecycle.models import (
    ACTION_STATUS_ASYNC_PENDING,
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_EXECUTING,
    ACTION_STATUS_FAILED,
    ACTION_STATUS_PENDING,
    ACTION_STATUS_PREVIEWED,
    ACTION_STATUS_SKIPPED,
    BATCH_PLAN_STATUS_ACTIVE,
    BLOCKED_REASON_CAPABILITY_UNDECLARED,
    HANDOVER_KIND_OFFBOARD,
    ITEM_STATUS_DONE,
    ITEM_STATUS_PENDING,
    ITEM_STATUS_SKIPPED,
    TASK_STATUS_CANCELLED,
    TEAM_ITEM_ACTION_ASSIGN_LEADER,
    TEAM_ITEM_ACTION_DEACTIVATE,
    HandoverActionSkipRecord,
    HandoverAppAction,
    HandoverAssetType,
    HandoverBatchPlan,
    HandoverExecutionLease,
    HandoverGrantItem,
    HandoverTask,
    HandoverTeamItem,
)
from easyauth.teams.models import TEAM_MEMBER_ROLE_LEADER, TeamMember

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror
    from easyauth.applications.ops_models import JsonValue


_BATCH_PLAN_IN_PROGRESS_MESSAGE: Final = "batch_plan_in_progress"
_GRANT_RECEIVER_NOT_ALLOWED_MESSAGE: Final = "grant_receiver_not_allowed"


def seed_asset_type_placeholders(action: HandoverAppAction) -> None:
    """按应用声明为交接动作建立资产类型占位。"""
    for item in action.app.handover_asset_types or []:
        if not isinstance(item, dict):
            continue
        type_key = str(item.get("type", ""))
        if not type_key:
            continue
        _ = HandoverAssetType.objects.get_or_create(
            action=action,
            generation=action.generation,
            type_key=type_key,
            defaults={
                "label_snapshot": str(item.get("label", type_key))[:120],
                "count": 0,
                "detail_supported": bool(item.get("detail_supported", False)),
                "releasable": bool(item.get("releasable", False)),
            },
        )


_RECEIVER_IS_SUBJECT_MESSAGE: Final = "receiver_is_subject"

# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def update_grant_receiver(
    *,
    action: HandoverAppAction,
    grant_receiver: UserMirror | None,
) -> HandoverAppAction:
    with transaction.atomic():
        locked = locked_action(action.id)
        ensure_task_open(locked.task)
        if assignment_mutation_in_flight(locked):
            raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
        plan = (
            HandoverBatchPlan.objects.select_for_update()
            .filter(
                action=locked,
                generation=locked.generation,
                status=BATCH_PLAN_STATUS_ACTIVE,
            )
            .first()
        )
        if plan is not None and plan.completed_batches > 0:
            raise HandoverConflictError(_BATCH_PLAN_IN_PROGRESS_MESSAGE)
        if grant_receiver is not None and locked.task.kind != HANDOVER_KIND_OFFBOARD:
            raise HandoverError(_GRANT_RECEIVER_NOT_ALLOWED_MESSAGE)
        if (
            grant_receiver is not None
            and cast("int", grant_receiver.pk) == locked.task.subject_user_id
        ):
            raise HandoverError(_RECEIVER_IS_SUBJECT_MESSAGE)
        locked.grant_receiver = grant_receiver
        locked.confirm_version += 1
        if locked.status in {ACTION_STATUS_FAILED, ACTION_STATUS_PREVIEWED}:
            locked.status = ACTION_STATUS_PENDING
            locked.snapshot_token = ""
            locked.last_error = ""
        locked.save(
            update_fields=[
                "grant_receiver",
                "confirm_version",
                "status",
                "snapshot_token",
                "last_error",
                "updated_at",
            ],
        )
        if plan is not None:
            _ = ensure_batch_plan_on_413(locked)
        return locked


# 兼容旧名: 控制台尚未迁完时避免 ImportError; 语义已变为 grant_receiver。
def update_action_receiver(
    *,
    action: HandoverAppAction,
    to_user: UserMirror | None,
    policy: dict[str, JsonValue] | None = None,
) -> HandoverAppAction:
    # 禁止静默丢弃: 旧 policy/release_to_pool 已无法兑现, 必须 400。
    if policy is not None and policy:
        raise HandoverError(POLICY_REMOVED_MESSAGE)
    return update_grant_receiver(action=action, grant_receiver=to_user)


def skip_action(
    action: HandoverAppAction,
    *,
    actor_id: str,
    reason: str = "",
) -> HandoverAppAction:
    with transaction.atomic():
        action = locked_action(action.id)
        ensure_action_status(
            action,
            allowed={
                ACTION_STATUS_PENDING,
                ACTION_STATUS_PREVIEWED,
                ACTION_STATUS_FAILED,
                ACTION_STATUS_BLOCKED,
            },
        )
        if action_execution_in_flight(action):
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        now = timezone.now()
        action.status = ACTION_STATUS_SKIPPED
        action.skip_reason = reason
        action.skipped_by = actor_id
        action.skipped_at = now
        action.save(
            update_fields=[
                "status",
                "skip_reason",
                "skipped_by",
                "skipped_at",
                "updated_at",
            ],
        )
        _ = HandoverActionSkipRecord.objects.create(
            task=action.task,
            task_id_snapshot=int(action.task_id),
            action_snapshot_id=int(action.id),
            generation=action.generation,
            app_key=action.app_key_snapshot or action.app.app_key,
            actor_id=actor_id,
            reason=reason,
        )
        _ = HandoverGrantItem.objects.filter(
            task=action.task,
            app=action.app,
            generation=action.generation,
            status=ITEM_STATUS_PENDING,
        ).update(status=ITEM_STATUS_SKIPPED)
        task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
        _ = refresh_task_status_locked(task)
    record_task_event(
        action.task,
        action="handover_action_skipped",
        actor_id=actor_id,
        extra={"app_key": action.app.app_key, "reason": reason},
    )
    return action


def apply_team_item(
    *,
    item: HandoverTeamItem,
    action: str,
    to_user: UserMirror | None,
    actor_id: str,
) -> HandoverTeamItem:
    with transaction.atomic():
        item = (
            HandoverTeamItem.objects.select_for_update(of=("self",))
            .select_related("task", "team")
            .get(pk=item.id)
        )
        ensure_task_open(item.task)
        if item.status != ITEM_STATUS_PENDING:
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        if action == TEAM_ITEM_ACTION_ASSIGN_LEADER:
            if to_user is None:
                message = "接任负责人时必须指定接收人。"
                raise HandoverError(message)
            if cast("int", to_user.pk) == item.task.subject_user_id:
                raise HandoverError(ACTION_SELF_RECEIVER_MESSAGE)
            _ = TeamMember.objects.update_or_create(
                team=item.team,
                user=to_user,
                defaults={"role": TEAM_MEMBER_ROLE_LEADER, "added_by": actor_id},
            )
        elif action == TEAM_ITEM_ACTION_DEACTIVATE:
            item.team.is_active = False
            item.team.save(update_fields=["is_active", "updated_at"])
        else:
            message = "团队交接动作必须为 assign_leader 或 deactivate。"
            raise HandoverError(message)
        item.action = action
        item.to_user = to_user
        item.status = ITEM_STATUS_DONE
        item.save()
        task = HandoverTask.objects.select_for_update().get(pk=item.task_id)
        _ = refresh_task_status_locked(task)
    record_task_event(
        item.task,
        action="handover_team_item_applied",
        actor_id=actor_id,
        extra={
            "team_name": item.team.name,
            "team_action": action,
            "to_user_id": to_user.authentik_user_id if to_user is not None else "",
        },
    )
    return item


def cancel_task(task: HandoverTask, *, actor_id: str) -> HandoverTask:
    with transaction.atomic():
        # §2.2 统一锁序: task → 子项
        task = HandoverTask.objects.select_for_update().get(pk=task.id)
        ensure_task_open(task)
        actions = list(
            HandoverAppAction.objects.select_for_update(of=("self",))
            .filter(task=task)
            .order_by("id"),
        )
        if (
            any(a.status in {ACTION_STATUS_EXECUTING, ACTION_STATUS_ASYNC_PENDING} for a in actions)
            or HandoverExecutionLease.objects.filter(
                action__task=task,
                released_at__isnull=True,
            ).exists()
        ):
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        for action in actions:
            if action.snapshot_token:
                action.snapshot_token = ""
                action.save(update_fields=["snapshot_token", "updated_at"])
        task.status = TASK_STATUS_CANCELLED
        task.escalation_deadline = None
        task.save(update_fields=["status", "escalation_deadline", "updated_at"])
    record_task_event(task, action="handover_task_cancelled", actor_id=actor_id)
    return task


def delete_task(task: HandoverTask, *, actor_id: str) -> None:
    with transaction.atomic():
        task = HandoverTask.objects.select_for_update().get(pk=task.id)
        if task.status != TASK_STATUS_CANCELLED:
            raise HandoverConflictError(TASK_NOT_DELETABLE_MESSAGE)
        if HandoverActionSkipRecord.objects.filter(task_id_snapshot=task.id).exists():
            message = "带有强行跳过历史的交接单不允许删除。"
            raise HandoverConflictError(message)
        record_task_event(task, action="handover_task_deleted", actor_id=actor_id)
        _ = task.delete()


def reset_action_for_upgrade(action: HandoverAppAction, *, task: HandoverTask) -> HandoverAppAction:
    """§5.1.2 升级字段重置。调用方已锁 task → action; 有未释放租约则 409。"""
    if has_active_lease(
        subject_user_id=int(task.subject_user_id),  # type: ignore[arg-type]
        app_id=int(action.app_id),  # type: ignore[arg-type]
    ):
        raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)

    action.generation = task.generation
    action.data_completed_at = None
    action.snapshot_token = ""
    action.batch_seq = 0
    action.last_error = ""
    action.last_error_raw = ""
    action.async_status_url = ""
    action.async_poll_attempts = 0
    action.skipped_at = None
    action.skipped_by = ""
    action.skip_reason = ""
    action.attempts = 0
    action.result_summary = None
    action.confirm_version += 1
    action.overrides_version += 1
    # status 按 capability 重判
    cap = action.app.handover_capability
    if cap == HANDOVER_CAPABILITY_DECLARED:
        action.status = ACTION_STATUS_PENDING
        action.blocked_reason = ""
    elif cap == HANDOVER_CAPABILITY_NONE:
        action.status = ACTION_STATUS_SKIPPED
        action.skip_reason = SKIP_REASON_CAPABILITY_NONE
        action.skipped_by = action.app.handover_capability_declared_by
        action.skipped_at = timezone.now()
        action.blocked_reason = ""
    else:
        action.status = ACTION_STATUS_BLOCKED
        action.blocked_reason = BLOCKED_REASON_CAPABILITY_UNDECLARED
    action.save()
    if action.status == ACTION_STATUS_PENDING:
        seed_asset_type_placeholders(action)
    return action


def initial_action_status_for_app(app: App) -> tuple[str, str, str, str]:
    """返回 (status, blocked_reason, skip_reason, skipped_by)。"""
    if app.handover_capability == HANDOVER_CAPABILITY_DECLARED:
        if not handover_hook_url(app):
            raise HandoverError(DECLARED_WITHOUT_URL_MESSAGE)
        return ACTION_STATUS_PENDING, "", "", ""
    if app.handover_capability == HANDOVER_CAPABILITY_NONE:
        return (
            ACTION_STATUS_SKIPPED,
            "",
            SKIP_REASON_CAPABILITY_NONE,
            app.handover_capability_declared_by,
        )
    return (
        ACTION_STATUS_BLOCKED,
        BLOCKED_REASON_CAPABILITY_UNDECLARED,
        "",
        "",
    )
