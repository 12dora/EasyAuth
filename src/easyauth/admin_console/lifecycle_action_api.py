"""处理生命周期交接应用动作的预览, 执行, 重试与跳过。"""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus
from typing import TYPE_CHECKING

from django.http import HttpRequest, JsonResponse
from pydantic import ValidationError

from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.lifecycle_api_serializers import (
    ExecuteConfirmPayload,
    SkipReasonPayload,
    not_found,
    task_or_none,
    validation_error,
)
from easyauth.api.errors import ErrorCode
from easyauth.lifecycle.api_errors import map_handover_exception, reason_error
from easyauth.lifecycle.api_payloads import SURFACE_CONSOLE, batch_progress
from easyauth.lifecycle.api_payloads import action_item as v2_action_item
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover import execute_action, retry_action
from easyauth.lifecycle.handover_actions import skip_action
from easyauth.lifecycle.handover_async import poll_async_action
from easyauth.lifecycle.handover_preview import preview_action
from easyauth.lifecycle.models import ACTION_STATUS_BLOCKED, HandoverAppAction
from easyauth.webhooks.hooks import HookCallError

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

type ActionOperation = Callable[
    [HandoverAppAction, str, HttpRequest | None],
    HandoverAppAction | JsonResponse,
]

# 跳过应用交接必须写明理由, 少于该长度视为未填。
_SKIP_REASON_MIN_LENGTH = 10


def lifecycle_action_operation(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    operation: str,
) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    task = task_or_none(task_id)
    if task is None:
        return not_found("交接单不存在。")
    action = (
        HandoverAppAction.objects.select_related(
            "app",
            "task",
            "task__subject_user",
            "grant_receiver",
        )
        .filter(task=task, app__app_key=app_key)
        .first()
    )
    if action is None:
        return not_found("交接单中不存在该应用。")
    return _run_action_operation(
        action,
        operation=operation,
        actor_id=actor_id,
        request=request,
    )


def _run_action_operation(
    action: HandoverAppAction,
    *,
    operation: str,
    actor_id: str,
    request: HttpRequest | None = None,
) -> JsonResponse:
    try:
        outcome = _dispatch_action_operation(
            action,
            operation=operation,
            actor_id=actor_id,
            request=request,
        )
    except HandoverConflictError as error:
        mapped = map_handover_exception(error)
        return mapped or error_response(
            ErrorCode.CONFLICT,
            str(error),
            {"reason": str(error)},
            status=HTTPStatus.CONFLICT,
        )
    except (HandoverError, HookCallError) as error:
        return _handover_failure_response(error, action=action)
    if isinstance(outcome, JsonResponse):
        return outcome
    return json_response({"action": v2_action_item(outcome, surface=SURFACE_CONSOLE)})


def _dispatch_action_operation(
    action: HandoverAppAction,
    *,
    operation: str,
    actor_id: str,
    request: HttpRequest | None,
) -> HandoverAppAction | JsonResponse:
    """把 operation 派发到对应的领域调用; 返回 JsonResponse 表示入参已判负。"""
    handlers: dict[str, ActionOperation] = {
        "preview": _preview_action_operation,
        "execute": _execute_action_operation,
        "retry": _retry_action_operation,
        "skip": _skip_action_operation,
    }
    handler = handlers.get(operation)
    if handler is None:
        return validation_error("操作必须为 preview、execute、retry 或 skip。")
    return handler(action, actor_id, request)


def _preview_action_operation(
    action: HandoverAppAction,
    _actor_id: str,
    _request: HttpRequest | None,
) -> HandoverAppAction | JsonResponse:
    if action.status == ACTION_STATUS_BLOCKED:
        return reason_error("action_blocked")
    return preview_action(action)


def _retry_action_operation(
    action: HandoverAppAction,
    _actor_id: str,
    _request: HttpRequest | None,
) -> HandoverAppAction:
    if action.status == "async_pending":
        return poll_async_action(action)
    return retry_action(action)


def _execute_action_operation(
    action: HandoverAppAction,
    _actor_id: str,
    request: HttpRequest | None,
) -> HandoverAppAction | JsonResponse:
    if action.status == ACTION_STATUS_BLOCKED:
        return reason_error("action_blocked")
    confirm_version = _confirm_version_from_body(request)
    if isinstance(confirm_version, JsonResponse):
        return confirm_version
    return execute_action(action, confirm_version=confirm_version)


def _skip_action_operation(
    action: HandoverAppAction,
    actor_id: str,
    request: HttpRequest | None,
) -> HandoverAppAction | JsonResponse:
    reason = _skip_reason_from_body(request)
    if isinstance(reason, JsonResponse):
        return reason
    return skip_action(action, actor_id=actor_id, reason=reason)


def _confirm_version_from_body(request: HttpRequest | None) -> int | None | JsonResponse:
    if request is None or not request.body:
        return _confirm_version_required()
    try:
        body = ExecuteConfirmPayload.model_validate_json(request.body)
    except ValidationError:
        return _confirm_version_required()
    return body.confirm_version


def _confirm_version_required() -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        "confirm_version 必填。",
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def _skip_reason_from_body(request: HttpRequest | None) -> str | JsonResponse:
    reason = ""
    if request is not None and request.body:
        try:
            body = SkipReasonPayload.model_validate_json(request.body)
            reason = body.reason.strip()
        except ValidationError:
            return reason_error("reason_required")
    if len(reason) < _SKIP_REASON_MIN_LENGTH:
        return reason_error("reason_required")
    return reason


def _handover_failure_response(
    error: HandoverError | HookCallError,
    *,
    action: HandoverAppAction,
) -> JsonResponse:
    """下游 412/413/423 会以 HandoverError 文本形态冒上来, 这里映射成稳定 reason。"""
    extra_details: dict[str, JsonValue] | None = None
    is_payload_too_large = (
        isinstance(error, HookCallError)
        and error.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    )
    if is_payload_too_large or "413" in str(error):
        action.refresh_from_db()
        extra_details = {"batch_progress": batch_progress(action)}
    mapped = map_handover_exception(error, details=extra_details)
    if mapped is not None:
        return mapped
    text = str(error)
    if "412" in text:
        return reason_error("snapshot_stale")
    if "413" in text:
        action.refresh_from_db()
        return reason_error(
            "payload_too_large",
            details={"batch_progress": batch_progress(action)},
        )
    if "423" in text:
        return reason_error("downstream_locked")
    return validation_error(text)
