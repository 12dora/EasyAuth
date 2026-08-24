"""处理控制台交接 v2 的动作错误读取与接收人更新。"""

from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.handover_v2_support import action_or_none, not_found
from easyauth.api.errors import ErrorCode
from easyauth.lifecycle.api_errors import map_handover_exception, reason_error
from easyauth.lifecycle.api_payloads import SURFACE_CONSOLE, action_item
from easyauth.lifecycle.core import record_task_event
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover_actions import update_grant_receiver


class GrantReceiverPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    grant_receiver_user_id: str | None = Field(default=None, max_length=128)


def console_handover_errors_raw(
    request: HttpRequest,
    task_id: int,
    app_key: str,
) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    action = action_or_none(task_id, app_key)
    if action is None:
        return not_found()
    # 每次读取先写审计
    record_task_event(
        action.task,
        action="handover_action_error_raw_viewed",
        actor_id=actor_id,
        actor_type="admin",
        extra={"app_key": app_key},
    )
    return json_response({"last_error_raw": action.last_error_raw})


def console_handover_action_patch(
    request: HttpRequest,
    task_id: int,
    app_key: str,
) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    if request.method != "PATCH":
        return method_not_allowed_response()
    return _patch_handover_action(request, task_id, app_key)


def _patch_handover_action(
    request: HttpRequest,
    task_id: int,
    app_key: str,
) -> JsonResponse:
    action = action_or_none(task_id, app_key)
    if action is None:
        return not_found()
    try:
        payload = GrantReceiverPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    receiver = None
    if payload.grant_receiver_user_id:
        receiver = UserMirror.objects.filter(
            authentik_user_id=payload.grant_receiver_user_id,
            status=USER_STATUS_ACTIVE,
        ).first()
        if receiver is None:
            return reason_error("receiver_not_active")
    try:
        action = update_grant_receiver(action=action, grant_receiver=receiver)
    except (HandoverConflictError, HandoverError) as error:
        mapped = map_handover_exception(error)
        return mapped or error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.BAD_REQUEST,
        )
    return json_response({"action": action_item(action, surface=SURFACE_CONSOLE)})
