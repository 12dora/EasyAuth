"""交接单/action 的 §6.2 响应形状。门户与控制台共享, 不含 HTTP 身份逻辑。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from django.db.models import Count, Q, Sum
from django.utils import timezone

from easyauth.api.datetime_json import datetime_value
from easyauth.audit.models import AuditLog
from easyauth.lifecycle.lease import action_execution_in_flight
from easyauth.lifecycle.models import (
    ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    ACTION_STATUS_ASYNC_PENDING,
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_EXECUTING,
    ACTION_STATUS_FAILED,
    ACTION_STATUS_PENDING,
    ACTION_STATUS_PREVIEWED,
    ASSIGNEE_STATE_SUPERUSER_POOL,
    BATCH_PLAN_STATUS_ACTIVE,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_COMPLETED,
    HandoverActionSkipRecord,
    HandoverAppAction,
    HandoverAssetType,
    HandoverBatchPlan,
    HandoverTask,
    HandoverTeamItem,
    TransferPlan,
)

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror
    from easyauth.api.errors import JsonValue

type JsonObject = dict[str, "JsonValue"]

SURFACE_PORTAL: Final = "portal"
SURFACE_CONSOLE: Final = "console"

_BASE_ALLOWED_ACTIONS: Final[dict[str, tuple[str, ...]]] = {
    ACTION_STATUS_PENDING: ("preview",),
    ACTION_STATUS_PREVIEWED: ("preview", "execute"),
    ACTION_STATUS_FAILED: ("retry",),
}
_CONSOLE_SKIPPABLE_STATUSES: Final = frozenset(
    {
        ACTION_STATUS_BLOCKED,
        ACTION_STATUS_PENDING,
        ACTION_STATUS_PREVIEWED,
        ACTION_STATUS_FAILED,
    },
)
_AUDIT_METADATA_TYPE_MESSAGE: Final = "审计 metadata 必须是 JSON 对象"


def user_ref(user: UserMirror | None, *, include_status: bool = False) -> JsonObject | None:
    if user is None:
        return None
    payload: JsonObject = {
        "user_id": user.authentik_user_id,
        "name": user.name,
        "department": user.department,
    }
    if include_status:
        payload["status"] = user.status
        payload["email"] = user.email
    return payload


def escalation_payload(
    task: HandoverTask,
    *,
    include_defer_history: bool = False,
) -> JsonObject:
    deadline = task.escalation_deadline
    days_left: int | None = None
    if deadline is not None and task.assignee_state != ASSIGNEE_STATE_SUPERUSER_POOL:
        delta = deadline - timezone.now()
        days_left = max(0, int(delta.total_seconds() // 86400))
    history: list[JsonValue] = []
    if include_defer_history:
        history = _defer_history_for_task(task)
    payload: JsonObject = {
        "deadline": datetime_value(deadline),
        "days_left": days_left,
        "level": task.escalation_level,
        "deferred_at": datetime_value(task.escalation_deferred_at),
        "defer_history": history,
    }
    return payload


def _defer_history_for_task(task: HandoverTask) -> list[JsonValue]:
    """从审计事件还原顺延责任链(01 §6.2 / §6.3)。"""
    rows = AuditLog.objects.filter(
        event_type="handover_task_deferred",
        target_type="handover_task",
        target_id=str(task.id),
    ).order_by("created_at", "id")
    history: list[JsonValue] = []
    for row in rows:
        meta = _validated_audit_metadata(row.metadata)
        level = meta.get("escalation_level", task.escalation_level)
        if not isinstance(level, int):
            if isinstance(level, (float, str)):
                try:
                    level = int(level)
                except (TypeError, ValueError):
                    level = task.escalation_level
            else:
                level = task.escalation_level
        history.append(
            {
                "escalation_level": level,
                "actor_id": row.actor_id,
                "at": datetime_value(row.created_at),
                "reason": str(meta.get("reason", "") or ""),
            },
        )
    return history


def _validated_audit_metadata(value: object) -> JsonObject:
    """校验数据库 JSON 元数据, 破坏对象契约时快速失败。"""
    if not isinstance(value, dict):
        raise TypeError(_AUDIT_METADATA_TYPE_MESSAGE)
    return cast("JsonObject", value)


def task_list_item(task: HandoverTask) -> JsonObject:
    actions = _task_actions(task)
    # 若未 prefetch, 再查一次聚合
    if not actions:
        actions = list(HandoverAppAction.objects.filter(task=task))
    pending = sum(1 for a in actions if a.status == ACTION_STATUS_PENDING)
    blocked = sum(1 for a in actions if a.status == ACTION_STATUS_BLOCKED)
    asset_count = (
        HandoverAssetType.objects.filter(
            action__task=task,
            generation=_latest_action_generation(actions),
        )
        .aggregate(total=Sum("count"))
        .get("total")
        or 0
    )
    total_asset = _current_generation_asset_count(actions)
    allowed: list[JsonValue] = []
    if task.status == TASK_STATUS_CANCELLED:
        allowed.append("delete")
    payload: JsonObject = {
        "id": task.id,
        "kind": task.kind,
        "status": task.status,
        "generation": task.generation,
        "subject": user_ref(task.subject_user, include_status=True),
        "assignee": user_ref(task.assignee),
        "assignee_state": task.assignee_state,
        "escalation_level": task.escalation_level,
        "escalation": escalation_payload(task),
        "reason": task.reason,
        "created_at": datetime_value(task.created_at),
        "pending_app_count": pending,
        "blocked_app_count": blocked,
        "total_asset_count": total_asset if total_asset else int(asset_count),
        "allowed_actions": allowed,
    }
    return payload


def _task_actions(task: HandoverTask) -> list[HandoverAppAction]:
    if hasattr(task, "_prefetched_objects_cache"):
        return list(task.app_actions.all())
    return list(HandoverAppAction.objects.filter(task=task))


def _current_generation_asset_count(actions: list[HandoverAppAction]) -> int:
    """按各 action 当前 generation 汇总资产数。"""
    total = 0
    for action in actions:
        total += (
            HandoverAssetType.objects.filter(
                action=action,
                generation=action.generation,
            )
            .aggregate(total=Sum("count"))
            .get("total")
            or 0
        )
    return total


def _latest_action_generation(actions: list[HandoverAppAction]) -> int:
    if not actions:
        return 1
    return max(a.generation for a in actions)


def task_detail(task: HandoverTask, *, surface: str = SURFACE_CONSOLE) -> JsonObject:
    actions_payload = _task_actions_payload(task, surface=surface)
    team_items = _task_team_items_payload(task)
    transfer_plan = _transfer_plan_payload(task)
    return {
        "id": task.id,
        "kind": task.kind,
        "status": task.status,
        "generation": task.generation,
        "subject": user_ref(task.subject_user, include_status=True),
        "assignee": user_ref(task.assignee),
        "assignee_state": task.assignee_state,
        "escalation_level": task.escalation_level,
        "escalation": escalation_payload(task, include_defer_history=True),
        "reason": task.reason,
        "created_at": datetime_value(task.created_at),
        "actions": actions_payload,
        "team_items": team_items,
        "transfer_plan": transfer_plan,
        "created_by": task.created_by,
        "updated_at": datetime_value(task.updated_at),
    }


def _task_actions_payload(task: HandoverTask, *, surface: str) -> list[JsonValue]:
    actions = HandoverAppAction.objects.select_related(
        "app",
        "grant_receiver",
        "task",
        "task__subject_user",
    ).filter(task=task)
    return [action_item(action, surface=surface) for action in actions]


def _task_team_items_payload(task: HandoverTask) -> list[JsonValue]:
    return [
        {
            "id": entry.id,
            "team_id": entry.team_id,
            "team_name": entry.team.name,
            "action": entry.action,
            "status": entry.status,
            "to_user": user_ref(entry.to_user),
        }
        for entry in HandoverTeamItem.objects.select_related("team", "to_user").filter(task=task)
    ]


def _transfer_plan_payload(task: HandoverTask) -> JsonObject | None:
    # transfer_plan: 控制台向导仍需要; 门户详情可空。
    plan = (
        TransferPlan.objects.select_related("new_template", "new_template_revision")
        .filter(task=task)
        .first()
    )
    if plan is None:
        return None
    template = plan.new_template
    template_revision = plan.new_template_revision
    grant_diff: dict[str, JsonValue] = dict(plan.grant_diff)
    if plan.confirmed_at is not None:
        _mark_selected_grants(
            grant_diff,
            confirmed_revoke_keys=set(plan.confirmed_revoke_keys),
            confirmed_add_keys=set(plan.confirmed_add_keys),
        )
    return {
        "template_id": template.id if template is not None else None,
        "template_name": template.name if template is not None else "",
        "template_revision_id": template_revision.id if template_revision is not None else None,
        "template_revision": (
            template_revision.revision if template_revision is not None else None
        ),
        "grant_diff": grant_diff,
        "revision": plan.revision,
        "confirmed_at": datetime_value(plan.confirmed_at),
    }


def _mark_selected_grants(
    grant_diff: dict[str, JsonValue],
    *,
    confirmed_revoke_keys: set[str],
    confirmed_add_keys: set[str],
) -> None:
    confirmed_by_name = {
        "revoke": confirmed_revoke_keys,
        "add": confirmed_add_keys,
    }
    for name, confirmed_keys in confirmed_by_name.items():
        entries = grant_diff.get(name)
        if not isinstance(entries, list):
            continue
        serialized: list[JsonValue] = [
            {**entry, "selected": entry.get("key") in confirmed_keys}
            for entry in entries
            if isinstance(entry, dict)
        ]
        grant_diff[name] = serialized


def action_item(action: HandoverAppAction, *, surface: str = SURFACE_CONSOLE) -> JsonObject:
    asset_types = list(
        HandoverAssetType.objects.select_related("default_to_user")
        .annotate(override_count=Count("overrides"))
        .filter(action=action, generation=action.generation),
    )
    skip_history: list[JsonValue] = [
        {
            "generation": rec.generation,
            "actor_id": rec.actor_id,
            "reason": rec.reason,
            "skipped_at": datetime_value(rec.skipped_at),
        }
        for rec in HandoverActionSkipRecord.objects.filter(
            Q(task=action.task) | Q(task_id_snapshot=action.task_id),
            app_key=action.app_key_snapshot or action.app.app_key,
        ).order_by("skipped_at", "id")
    ]
    allowed_actions: list[JsonValue] = []
    allowed_actions.extend(allowed_actions_for(action, surface=surface))
    payload: JsonObject = {
        "app_key": action.app_key_snapshot or action.app.app_key,
        "app_name": action.app_name_snapshot or action.app.name,
        "status": action.status,
        "blocked_reason": action.blocked_reason,
        "skip_reason": action.skip_reason,
        "last_error": action.last_error,
        "grant_receiver": user_ref(action.grant_receiver),
        "summary": aggregated_summary(action),
        "data_completed_at": datetime_value(action.data_completed_at),
        "confirm_version": action.confirm_version,
        "overrides_version": action.overrides_version,
        "skipped_by": action.skipped_by,
        "skipped_at": datetime_value(action.skipped_at),
        "skip_history": skip_history,
        "approval_instance_warning": action.approval_instance_warning,
        "allowed_actions": allowed_actions,
        "batch_progress": batch_progress(action),
        "asset_types": [asset_type_item(at) for at in asset_types],
    }
    return payload


def asset_type_item(asset_type: HandoverAssetType) -> JsonObject:
    override_count = getattr(asset_type, "override_count", None)
    if override_count is None:
        override_count = asset_type.overrides.count()
    return {
        "type": asset_type.type_key,
        "label": asset_type.label_snapshot,
        "count": asset_type.count,
        "detail_supported": asset_type.detail_supported,
        "releasable": asset_type.releasable,
        "default_action": asset_type.default_action,
        "default_to_user": user_ref(asset_type.default_to_user),
        "override_count": int(override_count),
    }


def batch_progress(action: HandoverAppAction) -> JsonObject | None:
    plan = (
        HandoverBatchPlan.objects.filter(
            action=action,
            generation=action.generation,
            status=BATCH_PLAN_STATUS_ACTIVE,
        )
        .order_by("-id")
        .first()
    )
    if plan is None:
        return None
    return {
        "completed": plan.completed_batches,
        "total": plan.total,
        "current_batch_seq": plan.completed_batches + 1,
    }


def aggregated_summary(action: HandoverAppAction) -> JsonObject | None:
    """各批 summary 逐字段相加的权威值: 直接读 action.result_summary(00 §10.5)。

    delivery.response_payload 经 redactor 后可能丢嵌套计数; result_summary 由
    ``_merge_result_summary`` 在 complete_data_phase 中维护, 是 API 侧真相源。
    """
    stored = getattr(action, "result_summary", None)
    if not isinstance(stored, dict) or not stored:
        return None
    # 某一批由管理员确认完成但未提供计数后, 后续批次即使有 summary, 也无法再构成
    # 冻结契约要求的全量累计值。人工处置事实留在审计 metadata, API summary 保持 null。
    if AuditLog.objects.filter(
        event_type="handover_action_executed",
        target_type="handover_task",
        target_id=str(action.task_id),
        metadata__manual_resolution=True,
        metadata__summary_provided=False,
        metadata__action_id=action.id,
        metadata__generation=action.generation,
    ).exists():
        return None
    if not _is_contract_summary(cast("dict[object, object]", stored)):
        return None
    return cast("JsonObject", stored)


def _is_contract_summary(summary: dict[object, object]) -> bool:
    fields = {"transferred", "released", "skipped", "merged", "failed"}
    return all(
        isinstance(type_key, str)
        and bool(type_key)
        and _is_contract_summary_row(row, fields=fields)
        for type_key, row in summary.items()
    )


def _is_contract_summary_row(row: object, *, fields: set[str]) -> bool:
    if not isinstance(row, dict):
        return False
    typed_row = cast("dict[object, object]", row)
    if set(typed_row) != fields:
        return False
    values = typed_row.values()
    return all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in values
    )


def allowed_actions_for(action: HandoverAppAction, *, surface: str) -> list[str]:
    """直接查 §10.6 可重试语义; 门户永不含 skip。"""
    if action.task.status in {TASK_STATUS_CANCELLED, TASK_STATUS_COMPLETED}:
        return []
    in_flight = action_execution_in_flight(action) or action.status in {
        ACTION_STATUS_EXECUTING,
        ACTION_STATUS_ASYNC_PENDING,
        ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    }
    allowed = list(_BASE_ALLOWED_ACTIONS.get(action.status, ()))
    if action.status == ACTION_STATUS_FAILED and in_flight:
        allowed.clear()
    if (
        surface == SURFACE_CONSOLE
        and not in_flight
        and action.status in _CONSOLE_SKIPPABLE_STATUSES
    ):
        allowed.append("skip")
    return allowed


def console_task_list_item(task: HandoverTask) -> JsonObject:
    item = task_list_item(task)
    # 控制台列表保留既有部分字段
    item["created_by"] = task.created_by
    item["updated_at"] = datetime_value(task.updated_at)
    return item
