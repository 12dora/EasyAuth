from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from django.db import transaction

from easyauth.accounts.models import UserMirror
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.models import (
    HANDOVER_KIND_TRANSFER,
    TASK_OPEN_STATUSES,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_COMPLETED,
    HandoverAppAction,
    HandoverTask,
    HandoverTeamItem,
    TransferPlan,
)
from easyauth.lifecycle.task_status import compute_task_status

if TYPE_CHECKING:
    from easyauth.applications.ops_models import JsonValue

LIFECYCLE_ACTOR_ID: Final = "lifecycle"
HOOK_EVENT_PREVIEW: Final = "lifecycle.handover.preview"
HOOK_EVENT_EXECUTE: Final = "lifecycle.handover.execute"
HOOK_EVENT_ITEMS: Final = "lifecycle.handover.items"
ASYNC_POLL_MAX_ATTEMPTS: Final = 10
ASYNC_ATTENTION_POLL_INTERVAL_SECONDS: Final = 30 * 60

TASK_NOT_OPEN_MESSAGE: Final = "交接单不在进行中状态。"
ACTION_RECEIVER_XOR_MESSAGE: Final = "接收人与释放公海策略必须严格二选一。"
ACTION_SELF_RECEIVER_MESSAGE: Final = "接收人不能是交接当事人本人。"
ACTION_RECEIVER_FROZEN_MESSAGE: Final = "交接已开始执行, 不允许更换接收人或释放策略。"
ACTION_NOT_OPERABLE_MESSAGE: Final = "该应用交接动作当前状态不允许执行此操作。"
TASK_KIND_CONFLICT_MESSAGE: Final = "该人员已有其他类型的进行中交接单。"
TRANSFER_CONFIRMATION_CONFLICT_MESSAGE: Final = "转岗差异已使用其他选择完成确认。"
TRANSFER_PLAN_STALE_MESSAGE: Final = "授权已在差异生成后发生变化, 请重新生成差异。"
TRANSFER_TEMPLATE_REVISION_MISSING_MESSAGE: Final = "岗位模板缺少当前修订, 请重新生成模板后再操作。"
TRANSFER_PLAN_REVISION_CONFLICT_MESSAGE: Final = "转岗差异方案或模板修订已更新, 请刷新后重新确认。"
TRANSFER_TASK_REQUIRED_MESSAGE: Final = "只有转岗单可以处理权限差异。"
ASYNC_STATUS_URL_REQUIRED_MESSAGE: Final = "异步交接缺少状态查询 URL。"
ASYNC_POLL_LIMIT_MESSAGE: Final = "异步交接状态查询已达到重试上限。"
ASYNC_ACCEPTED_LOCATION_REQUIRED_MESSAGE: Final = (
    "应用交接状态接口返回 202 时必须提供状态查询 URL。"
)
EXECUTE_ACCEPTED_LOCATION_REQUIRED_MESSAGE: Final = "应用交接接口返回 202 时必须提供状态查询 URL。"
PREVIEW_SYNC_REQUIRED_MESSAGE: Final = "应用交接预览接口必须同步返回 HTTP 200。"
PREVIEW_GENERATION_CONFLICT_MESSAGE: Final = "应用交接预览已被更新, 请刷新后重试。"
TEMPLATE_TERM_INVALID_MESSAGE: Final = "模板项期限配置无效。"
CATALOG_TARGET_DELETED_MESSAGE: Final = "授权目录项已删除, 无法执行交接。"
HOOK_NOT_DECLARED_RESULT: Final = "skipped"
HANDOVER_DATA_NOT_COMPLETED_MESSAGE: Final = "handover_data_not_completed"
HANDOVER_EXECUTION_IN_FLIGHT_MESSAGE: Final = "handover_execution_in_flight"

TASK_NOT_DELETABLE_MESSAGE: Final = (
    "只有已取消的交接单可以删除; 进行中的请先取消, 已完成的作为交接史料保留。"
)


def ensure_task_open(task: HandoverTask) -> None:
    if task.status not in TASK_OPEN_STATUSES:
        raise HandoverConflictError(TASK_NOT_OPEN_MESSAGE)


def ensure_transfer_task_open(task: HandoverTask) -> None:
    ensure_task_open(task)
    if task.kind != HANDOVER_KIND_TRANSFER:
        raise HandoverConflictError(TRANSFER_TASK_REQUIRED_MESSAGE)


def ensure_action_status(action: HandoverAppAction, *, allowed: set[str]) -> None:
    ensure_task_open(action.task)
    if action.status not in allowed:
        raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)


def validate_receiver_strategy(
    action: HandoverAppAction,
    *,
    to_user: UserMirror | None,
    policy: dict[str, JsonValue],
) -> None:
    # 旧 v1 路径遗留; v2 用 validate_assignments。保留给团队项等。
    releases_to_pool = policy.get("unowned_strategy") == "release_to_pool"
    if (to_user is not None) == releases_to_pool:
        raise HandoverError(ACTION_RECEIVER_XOR_MESSAGE)
    if to_user is not None and cast("int", to_user.pk) == action.task.subject_user_id:
        raise HandoverError(ACTION_SELF_RECEIVER_MESSAGE)


def record_task_event(
    task: HandoverTask,
    *,
    action: str,
    actor_id: str,
    actor_type: str | None = None,
    extra: dict[str, JsonValue] | None = None,
) -> None:
    resolved_actor_type = actor_type
    if resolved_actor_type is None:
        resolved_actor_type = (
            "system" if actor_id in {LIFECYCLE_ACTOR_ID, "directory_sync"} else "admin"
        )
    metadata: dict[str, JsonValue] = {
        "kind": task.kind,
        "subject_user_id": task.subject_user.authentik_user_id,
        "status": task.status,
    }
    if extra:
        metadata.update(extra)
    _ = AuditService.record(
        AuditRecord(
            actor_type=resolved_actor_type,
            actor_id=actor_id,
            action=action,
            target_type="handover_task",
            target_id=str(task.id),
            metadata=metadata,
        ),
    )


def refresh_task_status_locked(task: HandoverTask) -> HandoverTask:
    """调用方已 select_for_update 锁住 task; 与子状态同事务提交。"""
    if task.status not in TASK_OPEN_STATUSES and task.status != TASK_STATUS_CANCELLED:
        return task
    actions = list(HandoverAppAction.objects.filter(task=task))
    team_items = list(HandoverTeamItem.objects.filter(task=task))
    plan_confirmed = True
    if task.kind == HANDOVER_KIND_TRANSFER:
        plan = TransferPlan.objects.filter(task=task).first()
        plan_confirmed = plan is not None and plan.confirmed_at is not None
    nxt = compute_task_status(
        task,
        actions,
        team_items,
        plan_confirmed=plan_confirmed,
    )
    if task.status != nxt:
        previous = task.status
        task.status = nxt
        task.save(update_fields=["status", "updated_at"])
        if nxt == TASK_STATUS_COMPLETED:
            record_task_event(
                task,
                action="handover_task_completed",
                actor_id=LIFECYCLE_ACTOR_ID,
                actor_type="system",
            )
            if task.kind == HANDOVER_KIND_TRANSFER:
                _ = UserMirror.objects.filter(
                    pk=task.subject_user_id,
                    department_changed_at__isnull=False,
                ).update(department_changed_at=None)
        elif previous != nxt:
            # 允许任意方向变更, 含回退。
            pass
    return task


def refresh_task_status(task: HandoverTask) -> HandoverTask:
    with transaction.atomic():
        locked = HandoverTask.objects.select_for_update().get(pk=task.id)
        return refresh_task_status_locked(locked)
