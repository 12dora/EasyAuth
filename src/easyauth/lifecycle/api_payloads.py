"""交接单/action 的 §6.2 响应形状。门户与控制台共享, 不含 HTTP 身份逻辑。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from django.db.models import Count, Q, Sum
from django.utils import timezone

from easyauth.api.datetime_json import datetime_value
from easyauth.lifecycle.lease import action_execution_in_flight
from easyauth.lifecycle.models import (
    ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    ACTION_STATUS_ASYNC_PENDING,
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_DONE,
    ACTION_STATUS_EXECUTING,
    ACTION_STATUS_FAILED,
    ACTION_STATUS_PENDING,
    ACTION_STATUS_PREVIEWED,
    ASSIGNEE_STATE_SUPERUSER_POOL,
    BATCH_PLAN_STATUS_ACTIVE,
    BATCH_STATUS_DONE,
    DELIVERY_OUTCOME_SUCCEEDED,
    HandoverActionSkipRecord,
    HandoverAppAction,
    HandoverAssetType,
    HandoverBatchPlan,
    HandoverDeliveryAttempt,
    HandoverExecutionBatch,
    HandoverTask,
    HandoverTeamItem,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_COMPLETED,
)

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror
    from easyauth.api.errors import JsonValue

type JsonObject = dict[str, "JsonValue"]

SURFACE_PORTAL: Final = "portal"
SURFACE_CONSOLE: Final = "console"


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


def escalation_payload(task: HandoverTask) -> JsonObject:
    deadline = task.escalation_deadline
    days_left: int | None = None
    if deadline is not None and task.assignee_state != ASSIGNEE_STATE_SUPERUSER_POOL:
        delta = deadline - timezone.now()
        days_left = max(0, int(delta.total_seconds() // 86400))
    return {
        "deadline": datetime_value(deadline),
        "days_left": days_left,
        "level": task.escalation_level,
        "deferred_at": datetime_value(task.escalation_deferred_at),
        "defer_history": [],  # 由审计事件生成; 列表端点不强制扫审计
    }


def task_list_item(task: HandoverTask) -> JsonObject:
    actions = list(task.app_actions.all()) if hasattr(task, "_prefetched_objects_cache") else list(
        HandoverAppAction.objects.filter(task=task),
    )
    # 若未 prefetch, 再查一次聚合
    if not actions:
        actions = list(HandoverAppAction.objects.filter(task=task))
    pending = sum(1 for a in actions if a.status == ACTION_STATUS_PENDING)
    blocked = sum(1 for a in actions if a.status == ACTION_STATUS_BLOCKED)
    asset_count = (
        HandoverAssetType.objects.filter(
            action__task=task,
            generation=models_F_generation(actions),
        )
        .aggregate(total=Sum("count"))
        .get("total")
        or 0
    )
    # 按各 action 当前 generation 汇总更准
    total_asset = 0
    for action in actions:
        total_asset += (
            HandoverAssetType.objects.filter(
                action=action,
                generation=action.generation,
            )
            .aggregate(total=Sum("count"))
            .get("total")
            or 0
        )
    allowed: list[str] = []
    if task.status == TASK_STATUS_CANCELLED:
        allowed.append("delete")
    return {
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


def models_F_generation(actions: list[HandoverAppAction]) -> int:
    if not actions:
        return 1
    return max(a.generation for a in actions)


def task_detail(task: HandoverTask, *, surface: str = SURFACE_CONSOLE) -> JsonObject:
    actions_qs = HandoverAppAction.objects.select_related(
        "app",
        "grant_receiver",
        "task",
        "task__subject_user",
    ).filter(task=task)
    actions_payload: list[JsonValue] = [
        action_item(action, surface=surface) for action in actions_qs
    ]
    team_items: list[JsonValue] = [
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
    # transfer_plan: 控制台向导仍需要; 门户详情可空。
    transfer_plan: JsonObject | None = None
    from easyauth.lifecycle.models import TransferPlan

    plan = (
        TransferPlan.objects.select_related("new_template", "new_template_revision")
        .filter(task=task)
        .first()
    )
    if plan is not None:
        template = plan.new_template
        template_revision = plan.new_template_revision
        grant_diff: dict[str, JsonValue] = dict(plan.grant_diff)
        if plan.confirmed_at is not None:
            confirmed_by_name = {
                "revoke": set(plan.confirmed_revoke_keys),
                "add": set(plan.confirmed_add_keys),
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
        transfer_plan = {
            "template_id": template.id if template is not None else None,
            "template_name": template.name if template is not None else "",
            "template_revision_id": (
                template_revision.id if template_revision is not None else None
            ),
            "template_revision": (
                template_revision.revision if template_revision is not None else None
            ),
            "grant_diff": grant_diff,
            "revision": plan.revision,
            "confirmed_at": datetime_value(plan.confirmed_at),
        }
    return {
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
        "actions": actions_payload,
        "team_items": team_items,
        "transfer_plan": transfer_plan,
        "created_by": task.created_by,
        "updated_at": datetime_value(task.updated_at),
    }


def action_item(action: HandoverAppAction, *, surface: str = SURFACE_CONSOLE) -> JsonObject:
    asset_types = list(
        HandoverAssetType.objects.select_related("default_to_user")
        .annotate(override_count=Count("overrides"))
        .filter(action=action, generation=action.generation),
    )
    skip_history = [
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
    return {
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
        "allowed_actions": allowed_actions_for(action, surface=surface),
        "batch_progress": batch_progress(action),
        "asset_types": [asset_type_item(at) for at in asset_types],
    }


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
    """各批成功 delivery 的 summary 逐字段相加(00 §10.5)。"""
    if action.status != ACTION_STATUS_DONE and action.data_completed_at is None:
        # 进行中不展示; done 或 data 已完成时可能有部分 summary
        if action.status not in {ACTION_STATUS_DONE, ACTION_STATUS_FAILED}:
            return None
    batches = HandoverExecutionBatch.objects.filter(
        action=action,
        generation=action.generation,
        status__in={BATCH_STATUS_DONE, "data_completed"},
    )
    totals: dict[str, dict[str, int]] = {}
    found = False
    for batch in batches:
        delivery = (
            HandoverDeliveryAttempt.objects.filter(
                batch=batch,
                outcome=DELIVERY_OUTCOME_SUCCEEDED,
            )
            .order_by("-id")
            .first()
        )
        if delivery is None:
            continue
        payload = delivery.response_payload or {}
        summary = payload.get("summary")
        if not isinstance(summary, dict):
            # _redact 会把 summary 嵌在 summary.summary
            nested = payload.get("summary")
            if isinstance(nested, dict) and isinstance(nested.get("summary"), dict):
                summary = nested["summary"]
            else:
                continue
        found = True
        for type_key, row in summary.items():
            if not isinstance(type_key, str) or not isinstance(row, dict):
                continue
            bucket = totals.setdefault(
                type_key,
                {"transferred": 0, "released": 0, "skipped": 0, "merged": 0, "failed": 0},
            )
            for field in bucket:
                val = row.get(field, 0)
                if isinstance(val, int):
                    bucket[field] += val
    if not found:
        stored = getattr(action, "result_summary", None)
        if isinstance(stored, dict) and stored:
            return stored  # type: ignore[return-value]
        return None
    return totals  # type: ignore[return-value]


def allowed_actions_for(action: HandoverAppAction, *, surface: str) -> list[str]:
    """直接查 §10.6 可重试语义; 门户永不含 skip。"""
    if action.task.status in {TASK_STATUS_CANCELLED, TASK_STATUS_COMPLETED}:
        return []
    in_flight = action_execution_in_flight(action) or action.status in {
        ACTION_STATUS_EXECUTING,
        ACTION_STATUS_ASYNC_PENDING,
        ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    }
    allowed: list[str] = []
    if action.status == ACTION_STATUS_BLOCKED:
        if surface == SURFACE_CONSOLE and not in_flight:
            allowed.append("skip")
        return allowed
    if action.status == ACTION_STATUS_PENDING:
        allowed.append("preview")
        if surface == SURFACE_CONSOLE and not in_flight:
            allowed.append("skip")
        return allowed
    if action.status == ACTION_STATUS_PREVIEWED:
        allowed.extend(["preview", "execute"])
        if surface == SURFACE_CONSOLE and not in_flight:
            allowed.append("skip")
        return allowed
    if action.status == ACTION_STATUS_FAILED and not in_flight:
        allowed.append("retry")
        if surface == SURFACE_CONSOLE:
            allowed.append("skip")
        return allowed
    if action.status == ACTION_STATUS_ASYNC_ATTENTION_REQUIRED and surface == SURFACE_CONSOLE:
        # async-abandon 是独立端点, 不进 allowed_actions 四元组
        return []
    return allowed


def console_task_list_item(task: HandoverTask) -> JsonObject:
    item = task_list_item(task)
    # 控制台列表保留既有部分字段
    item["created_by"] = task.created_by
    item["updated_at"] = datetime_value(task.updated_at)
    return item
