"""处理生命周期交接任务的授权项选择与团队项操作。"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from pydantic import ValidationError

from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.lifecycle_api_serializers import (
    GrantItemsPatchPayload,
    TeamItemPatchPayload,
    active_user_or_none,
    grant_item,
    not_found,
    task_or_none,
    team_item,
    validation_error,
)
from easyauth.api.errors import ErrorCode
from easyauth.lifecycle.core import refresh_task_status
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover_actions import apply_team_item
from easyauth.lifecycle.models import (
    HandoverAppAction,
    HandoverGrantItem,
    HandoverTask,
    HandoverTeamItem,
)

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue


def lifecycle_grant_items(
    request: HttpRequest,
    task_id: int,
) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    task = task_or_none(task_id)
    if task is None:
        return not_found("交接单不存在。")
    if request.method == "GET":
        return lifecycle_grant_items_readback(task)
    if request.method == "PATCH":
        return _patch_grant_items(request, task)
    return method_not_allowed_response()


def _patch_grant_items(request: HttpRequest, task: HandoverTask) -> JsonResponse:
    try:
        payload = GrantItemsPatchPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return validation_error("勾选参数无效。", {"errors": str(exc)})
    selection = {entry.id: entry.selected for entry in payload.items}
    if len(selection) != len(payload.items):
        return validation_error("同一授权快照项不能重复提交。")
    with transaction.atomic():
        error = _apply_grant_item_selection(task, selection)
        if error is not None:
            return error
    return lifecycle_grant_items_readback(task)


def _apply_grant_item_selection(
    task: HandoverTask,
    selection: dict[int, bool],
) -> JsonResponse | None:
    locked_task = HandoverTask.objects.select_for_update().get(pk=task.id)
    if locked_task.status not in {"pending", "in_progress"}:
        return error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            "交接单不在进行中状态。",
            status=HTTPStatus.CONFLICT,
        )
    editable = list(
        HandoverGrantItem.objects.select_for_update().filter(
            task=locked_task,
            id__in=selection,
            status="pending",
        ),
    )
    if len(editable) != len(selection):
        return error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            "授权快照项不存在或已处理。",
            status=HTTPStatus.CONFLICT,
        )
    changed_app_ids = _update_grant_item_selection(editable, selection)
    if changed_app_ids:
        _reset_changed_grant_actions(locked_task, changed_app_ids)
    return None


def _update_grant_item_selection(
    editable: list[HandoverGrantItem],
    selection: dict[int, bool],
) -> set[int]:
    changed_app_ids: set[int] = set()
    for item in editable:
        selected = selection[item.id]
        if item.selected == selected:
            continue
        item.selected = selected
        item.save(update_fields=["selected"])
        changed_app_ids.add(item.app_id)
    return changed_app_ids


def _reset_changed_grant_actions(
    task: HandoverTask,
    changed_app_ids: set[int],
) -> None:
    actions = HandoverAppAction.objects.select_for_update().filter(
        task=task,
        app_id__in=changed_app_ids,
        status="previewed",
    )
    for action in actions:
        action.status = "pending"
        action.snapshot_token = ""
        action.last_error = ""
        action.save(
            update_fields=["status", "snapshot_token", "last_error", "updated_at"],
        )


def lifecycle_grant_items_readback(task: HandoverTask) -> JsonResponse:
    items: list[JsonValue] = [
        grant_item(item)
        for item in HandoverGrantItem.objects.select_related(
            "app",
            "authorization_group",
            "permission",
        ).filter(task=task)
    ]
    return json_response({"data": items})


def lifecycle_team_item_detail(
    request: HttpRequest,
    task_id: int,
    item_id: int,
) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "PATCH":
        return method_not_allowed_response()
    task = task_or_none(task_id)
    if task is None:
        return not_found("交接单不存在。")
    item = (
        HandoverTeamItem.objects.select_related("team", "task", "task__subject_user")
        .filter(task=task, id=item_id)
        .first()
    )
    if item is None:
        return not_found("交接单中不存在该团队。")
    return _apply_team_item_request(request, item, actor_id=actor_id)


def _apply_team_item_request(
    request: HttpRequest,
    item: HandoverTeamItem,
    *,
    actor_id: str,
) -> JsonResponse:
    try:
        payload = TeamItemPatchPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return validation_error("团队交接参数无效。", {"errors": str(exc)})
    to_user = None
    if payload.to_user_id:
        to_user = active_user_or_none(payload.to_user_id)
        if to_user is None:
            return validation_error("接收人不存在或已停用。")
    try:
        item = apply_team_item(
            item=item,
            action=payload.action,
            to_user=to_user,
            actor_id=actor_id,
        )
    except HandoverConflictError as error:
        return error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.CONFLICT,
        )
    except HandoverError as error:
        return validation_error(str(error))
    _ = refresh_task_status(item.task)
    return json_response({"team_item": team_item(item)})
