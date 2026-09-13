"""交接 action / 资产 / 团队条目的 §6.2 响应形状。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from django.db.models import Count, Q

from easyauth.api.datetime_json import datetime_value
from easyauth.audit.models import AuditLog
from easyauth.lifecycle.api_payloads_people import user_ref
from easyauth.lifecycle.lease import action_execution_in_flight
from easyauth.lifecycle.models import (
    ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    ACTION_STATUS_ASYNC_PENDING,
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_EXECUTING,
    ACTION_STATUS_FAILED,
    ACTION_STATUS_PENDING,
    ACTION_STATUS_PREVIEWED,
    BATCH_PLAN_STATUS_ACTIVE,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_COMPLETED,
    HandoverActionSkipRecord,
    HandoverAppAction,
    HandoverAssetType,
    HandoverBatchPlan,
    HandoverTeamItem,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from easyauth.api.errors import JsonValue
    from easyauth.lifecycle.api_payloads_people import JsonObject

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

__all__ = [
    "SURFACE_CONSOLE",
    "SURFACE_PORTAL",
    "_asset_types_for_action",
    "_task_team_items_payload",
    "action_item",
    "aggregated_summary",
    "allowed_actions_for",
    "asset_type_item",
    "batch_progress",
    "team_item",
]


def team_item(
    entry: HandoverTeamItem,
    *,
    department_labels: Mapping[str, str] | None = None,
) -> JsonObject:
    return {
        "id": entry.id,
        "team_id": entry.team_id,
        "team_name": entry.team.name,
        "action": entry.action,
        "status": entry.status,
        "to_user": user_ref(entry.to_user, department_labels=department_labels),
    }


def _task_team_items_payload(
    entries: list[HandoverTeamItem],
    *,
    department_labels: Mapping[str, str] | None = None,
) -> list[JsonValue]:
    return [team_item(entry, department_labels=department_labels) for entry in entries]


def action_item(
    action: HandoverAppAction,
    *,
    surface: str = SURFACE_CONSOLE,
    department_labels: Mapping[str, str] | None = None,
) -> JsonObject:
    asset_types = _asset_types_for_action(action)
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
        "app_alias": action.app.alias,
        "status": action.status,
        "blocked_reason": action.blocked_reason,
        "skip_reason": action.skip_reason,
        "last_error": action.last_error,
        "grant_receiver": user_ref(
            action.grant_receiver,
            department_labels=department_labels,
        ),
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
        "asset_types": [
            asset_type_item(at, department_labels=department_labels) for at in asset_types
        ],
    }
    return payload


def _asset_types_for_action(action: HandoverAppAction) -> list[HandoverAssetType]:
    cache = getattr(action, "_prefetched_objects_cache", None)
    if isinstance(cache, dict) and "asset_types" in cache:
        return [
            asset_type
            for asset_type in action.asset_types.all()
            if asset_type.generation == action.generation
        ]
    return list(
        HandoverAssetType.objects.select_related("default_to_user")
        .annotate(override_count=Count("overrides"))
        .filter(action=action, generation=action.generation),
    )


def asset_type_item(
    asset_type: HandoverAssetType,
    *,
    department_labels: Mapping[str, str] | None = None,
) -> JsonObject:
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
        "default_to_user": user_ref(
            asset_type.default_to_user,
            department_labels=department_labels,
        ),
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
