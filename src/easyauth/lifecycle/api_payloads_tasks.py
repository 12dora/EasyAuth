"""交接单列表/详情的 §6.2 响应形状。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from django.db.models import Count, Prefetch, Sum
from django.utils import timezone

from easyauth.accounts.department_paths import department_path_labels
from easyauth.api.datetime_json import datetime_value
from easyauth.audit.models import AuditLog
from easyauth.lifecycle.api_payloads_actions import (
    SURFACE_CONSOLE,
    _asset_types_for_action,
    _task_team_items_payload,
    action_item,
)
from easyauth.lifecycle.api_payloads_people import (
    _created_by_person,
    _person_or_none,
    _users_by_ids,
    user_ref,
)
from easyauth.lifecycle.models import (
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_PENDING,
    ASSIGNEE_STATE_SUPERUSER_POOL,
    TASK_STATUS_CANCELLED,
    HandoverAppAction,
    HandoverAssetType,
    HandoverTask,
    HandoverTeamItem,
    TransferPlan,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from easyauth.accounts.models import UserMirror
    from easyauth.api.errors import JsonValue
    from easyauth.lifecycle.api_payloads_people import JsonObject

_AUDIT_METADATA_TYPE_MESSAGE: Final = "审计 metadata 必须是 JSON 对象"

__all__ = [
    "console_task_list_item",
    "escalation_payload",
    "task_detail",
    "task_list_item",
]


def escalation_payload(
    task: HandoverTask,
    *,
    include_defer_history: bool = False,
    defer_rows: tuple[AuditLog, ...] | None = None,
    people: Mapping[str, UserMirror] | None = None,
    department_labels: Mapping[str, str] | None = None,
) -> JsonObject:
    deadline = task.escalation_deadline
    days_left: int | None = None
    if deadline is not None and task.assignee_state != ASSIGNEE_STATE_SUPERUSER_POOL:
        delta = deadline - timezone.now()
        days_left = max(0, int(delta.total_seconds() // 86400))
    history: list[JsonValue] = []
    if include_defer_history:
        history = _defer_history_for_task(
            task,
            rows=defer_rows,
            people=people,
            department_labels=department_labels,
        )
    payload: JsonObject = {
        "deadline": datetime_value(deadline),
        "days_left": days_left,
        "level": task.escalation_level,
        "deferred_at": datetime_value(task.escalation_deferred_at),
        "defer_history": history,
    }
    return payload


def _defer_history_rows(task: HandoverTask) -> tuple[AuditLog, ...]:
    return tuple(
        AuditLog.objects.filter(
            event_type="handover_task_deferred",
            target_type="handover_task",
            target_id=str(task.id),
        ).order_by("created_at", "id"),
    )


def _defer_history_for_task(
    task: HandoverTask,
    *,
    rows: tuple[AuditLog, ...] | None = None,
    people: Mapping[str, UserMirror] | None = None,
    department_labels: Mapping[str, str] | None = None,
) -> list[JsonValue]:
    """从审计事件还原顺延责任链(01 §6.2 / §6.3)。"""
    history_rows = _defer_history_rows(task) if rows is None else rows
    resolved_people = (
        people if people is not None else _users_by_ids(row.actor_id for row in history_rows)
    )
    labels = (
        department_labels
        if department_labels is not None
        else department_path_labels(resolved_people.values())
    )
    history: list[JsonValue] = []
    for row in history_rows:
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
                "actor_person": _person_or_none(
                    row.actor_id,
                    people=resolved_people,
                    department_labels=labels,
                ),
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


def task_list_item(
    task: HandoverTask,
    *,
    department_labels: Mapping[str, str] | None = None,
    people: Mapping[str, UserMirror] | None = None,
) -> JsonObject:
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
        "subject": user_ref(
            task.subject_user,
            include_status=True,
            department_labels=department_labels,
        ),
        "assignee": user_ref(task.assignee, department_labels=department_labels),
        "assignee_state": task.assignee_state,
        "escalation_level": task.escalation_level,
        "escalation": escalation_payload(task),
        "reason": task.reason,
        "created_at": datetime_value(task.created_at),
        "created_by_person": _created_by_person(
            task,
            people=people,
            department_labels=department_labels,
        ),
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
    actions = _task_detail_actions(task)
    team_entries = list(
        HandoverTeamItem.objects.select_related("team", "to_user").filter(task=task),
    )
    defer_rows = _defer_history_rows(task)
    related_users = _task_detail_users(task, actions, team_entries)
    people = {user.authentik_user_id: user for user in related_users}
    extra_ids = (task.created_by, *(row.actor_id for row in defer_rows))
    missing = tuple(
        user_id for user_id in dict.fromkeys(extra_ids) if user_id and user_id not in people
    )
    if missing:
        people.update(_users_by_ids(missing))
    department_labels = department_path_labels(people.values())
    transfer_plan = _transfer_plan_payload(task)
    return {
        "id": task.id,
        "kind": task.kind,
        "status": task.status,
        "generation": task.generation,
        "subject": user_ref(
            task.subject_user,
            include_status=True,
            department_labels=department_labels,
        ),
        "assignee": user_ref(task.assignee, department_labels=department_labels),
        "assignee_state": task.assignee_state,
        "escalation_level": task.escalation_level,
        "escalation": escalation_payload(
            task,
            include_defer_history=True,
            defer_rows=defer_rows,
            people=people,
            department_labels=department_labels,
        ),
        "reason": task.reason,
        "created_at": datetime_value(task.created_at),
        "actions": [
            action_item(action, surface=surface, department_labels=department_labels)
            for action in actions
        ],
        "team_items": _task_team_items_payload(
            team_entries,
            department_labels=department_labels,
        ),
        "transfer_plan": transfer_plan,
        "created_by": task.created_by,
        "created_by_person": _person_or_none(
            task.created_by,
            people=people,
            department_labels=department_labels,
        ),
        "updated_at": datetime_value(task.updated_at),
    }


def _task_detail_actions(task: HandoverTask) -> list[HandoverAppAction]:
    return list(
        HandoverAppAction.objects.select_related(
            "app",
            "grant_receiver",
            "task",
            "task__subject_user",
        )
        .prefetch_related(
            Prefetch(
                "asset_types",
                queryset=HandoverAssetType.objects.select_related("default_to_user").annotate(
                    override_count=Count("overrides"),
                ),
            ),
        )
        .filter(task=task),
    )


def _task_detail_users(
    task: HandoverTask,
    actions: list[HandoverAppAction],
    team_entries: list[HandoverTeamItem],
) -> list[UserMirror]:
    users: list[UserMirror] = []
    seen: set[str] = set()
    candidates: list[UserMirror | None] = [task.subject_user, task.assignee]
    candidates.extend(action.grant_receiver for action in actions)
    candidates.extend(
        asset_type.default_to_user
        for action in actions
        for asset_type in _asset_types_for_action(action)
    )
    candidates.extend(entry.to_user for entry in team_entries)
    for user in candidates:
        if user is None or user.authentik_user_id in seen:
            continue
        seen.add(user.authentik_user_id)
        users.append(user)
    return users


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


def console_task_list_item(
    task: HandoverTask,
    *,
    department_labels: Mapping[str, str] | None = None,
    people: Mapping[str, UserMirror] | None = None,
) -> JsonObject:
    item = task_list_item(task, department_labels=department_labels, people=people)
    # 控制台列表保留既有部分字段
    item["created_by"] = task.created_by
    item["updated_at"] = datetime_value(task.updated_at)
    return item
