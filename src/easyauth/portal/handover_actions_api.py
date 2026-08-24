"""提供门户交接动作修改, 执行和错误映射端点。"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.responses import error_response, json_response
from easyauth.lifecycle.api_errors import map_handover_exception, reason_error
from easyauth.lifecycle.api_payloads import SURFACE_PORTAL, action_item, batch_progress
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover import execute_action, retry_action
from easyauth.lifecycle.handover_actions import update_grant_receiver
from easyauth.lifecycle.handover_preview import preview_action
from easyauth.lifecycle.models import ACTION_STATUS_BLOCKED, HandoverAppAction
from easyauth.portal.handover_api import (
    PORTAL_ASSIGNEE_REQUIRED,
    action_for_user,
    not_found,
    portal_mutation_guard,
    portal_user_for_method,
    recheck_reassign_scope_locked,
)
from easyauth.webhooks.hooks import HookCallError

if TYPE_CHECKING:
    from easyauth.lifecycle.handover_shared import MutationGuard


class GrantReceiverPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    grant_receiver_user_id: str | None = Field(max_length=128)


class ExecutePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    confirm_version: int = Field(ge=0)


def portal_handover_action_patch(
    request: HttpRequest,
    task_id: int,
    app_key: str,
) -> JsonResponse:
    match portal_user_for_method(request, "PATCH"):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    receiver = _grant_receiver_from_request(request)
    if isinstance(receiver, JsonResponse):
        return receiver
    try:
        with transaction.atomic():
            action = action_for_user(
                user,
                task_id,
                app_key,
                require_assignee=True,
                lock_for_mutation=True,
            )
            if isinstance(action, JsonResponse):
                return action
            action = update_grant_receiver(action=action, grant_receiver=receiver)
    except (HandoverConflictError, HandoverError) as error:
        mapped = map_handover_exception(error)
        return mapped or error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.BAD_REQUEST,
        )
    return json_response({"action": action_item(action, surface=SURFACE_PORTAL)})


def portal_handover_action_operation(
    request: HttpRequest,
    task_id: int,
    app_key: str,
    operation: str,
) -> JsonResponse:
    match portal_user_for_method(request, "POST"):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    action = action_for_user(user, task_id, app_key, require_assignee=True)
    if isinstance(action, JsonResponse):
        return action
    if action.status == ACTION_STATUS_BLOCKED and operation in {"preview", "execute"}:
        return reason_error("action_blocked")
    mutation_guard = portal_mutation_guard(user)
    try:
        outcome = _dispatch_portal_action(
            action,
            operation=operation,
            request=request,
            mutation_guard=mutation_guard,
        )
    except (HandoverConflictError, HandoverError, HookCallError) as error:
        return _portal_action_error_response(error, action=action, task_id=task_id, user=user)
    if isinstance(outcome, JsonResponse):
        return outcome
    return json_response({"action": action_item(outcome, surface=SURFACE_PORTAL)})


def _dispatch_portal_action(
    action: HandoverAppAction,
    *,
    operation: str,
    request: HttpRequest,
    mutation_guard: MutationGuard,
) -> HandoverAppAction | JsonResponse:
    """把 operation 派发到对应的领域调用; 返回 JsonResponse 表示入参已判负。"""
    if operation == "preview":
        return preview_action(action, mutation_guard=mutation_guard)
    if operation == "execute":
        try:
            body = ExecutePayload.model_validate_json(request.body or b"{}")
        except ValidationError:
            return error_response(
                ErrorCode.VALIDATION_ERROR,
                "confirm_version 必填。",
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        return execute_action(
            action,
            confirm_version=body.confirm_version,
            mutation_guard=mutation_guard,
        )
    if operation == "retry":
        return retry_action(action, mutation_guard=mutation_guard)
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        "操作必须为 preview、execute 或 retry。",
        status=HTTPStatus.BAD_REQUEST,
    )


def _portal_scope_error_response(
    error: HandoverError | HookCallError,
    *,
    task_id: int,
    user: UserMirror,
) -> JsonResponse | None:
    """门户特有的前置映射: 非受理人一律 404; 管辖权失效要先复核并可能回收 reassign。"""
    if str(error) == PORTAL_ASSIGNEE_REQUIRED:
        return not_found()
    if str(error) in {"out_of_managed_scope", "directory_unavailable"}:
        revoked = recheck_reassign_scope_locked(task_id, user)
        if isinstance(revoked, JsonResponse):
            return revoked
    return None


def _portal_action_error_response(
    error: HandoverError | HookCallError,
    *,
    action: HandoverAppAction,
    task_id: int,
    user: UserMirror,
) -> JsonResponse:
    """管辖权失效要先复核 reassign 授权; 下游 412/413/423 映射成稳定 reason。"""
    scoped = _portal_scope_error_response(error, task_id=task_id, user=user)
    if scoped is not None:
        return scoped
    extra_details: dict[str, JsonValue] | None = None
    if (
        isinstance(error, HookCallError)
        and error.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    ) or "413" in str(error):
        action.refresh_from_db()
        extra_details = {"batch_progress": batch_progress(action)}
    mapped = map_handover_exception(error, details=extra_details)
    if mapped is not None:
        return mapped
    text = str(error)
    # 412/413/423 from downstream may surface as HandoverError with HTTP hint
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
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        text,
        status=HTTPStatus.BAD_REQUEST,
    )


def _grant_receiver_from_request(request: HttpRequest) -> UserMirror | JsonResponse | None:
    try:
        payload = GrantReceiverPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    if not payload.grant_receiver_user_id:
        return None
    receiver = UserMirror.objects.filter(
        authentik_user_id=payload.grant_receiver_user_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    if receiver is None:
        return reason_error("receiver_not_active")
    return receiver
