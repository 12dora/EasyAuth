from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.access_requests.approvals import (
    ApprovalActionError,
    ApprovalDecision,
    access_request_approver_user_ids,
    approve_access_request,
    reassign_access_request,
    reject_access_request,
)
from easyauth.access_requests.models import DECISION_ACTOR_CONSOLE_ADMIN, AccessRequest
from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode, JsonValue


class _AdminDecisionPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    comment: str = Field(default="", max_length=2000)


class _ReassignPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    approver_user_ids: list[str] = Field(min_length=1, max_length=20)


def operations_approve_access_request(request: HttpRequest, request_id: int) -> JsonResponse:
    return _admin_decide(request, request_id, action="approve")


def operations_reject_access_request(request: HttpRequest, request_id: int) -> JsonResponse:
    return _admin_decide(request, request_id, action="reject")


def operations_reassign_access_request(request: HttpRequest, request_id: int) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return _method_not_allowed()
    try:
        payload = _ReassignPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _invalid_payload_response(exc)
    try:
        access_request = reassign_access_request(
            request_id=request_id,
            approver_user_ids=payload.approver_user_ids,
            actor_id=actor_id,
        )
    except ApprovalActionError as exc:
        return _approval_error_response(exc)
    return _json_response({"access_request": _request_item(access_request)})


def _admin_decide(request: HttpRequest, request_id: int, *, action: str) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return _method_not_allowed()
    try:
        payload = _AdminDecisionPayload.model_validate_json(request.body or b"{}")
    except ValidationError as exc:
        return _invalid_payload_response(exc)
    decision = ApprovalDecision(
        actor_type=DECISION_ACTOR_CONSOLE_ADMIN,
        actor_id=actor_id,
        comment=payload.comment,
    )
    try:
        if action == "approve":
            access_request = approve_access_request(request_id=request_id, decision=decision)
        else:
            access_request = reject_access_request(request_id=request_id, decision=decision)
    except ApprovalActionError as exc:
        return _approval_error_response(exc)
    return _json_response({"access_request": _request_item(access_request)})


def _request_item(access_request: AccessRequest) -> dict[str, JsonValue]:
    approver_ids: list[JsonValue] = []
    approver_ids.extend(access_request_approver_user_ids(access_request))
    return {
        "id": access_request.id,
        "user_id": access_request.user.authentik_user_id,
        "app_key": access_request.app.app_key,
        "status": access_request.status,
        "approver_user_ids": approver_ids,
        "decided_by": access_request.decided_by,
        "decision_actor_type": access_request.decision_actor_type,
        "decision_comment": access_request.decision_comment,
        "decided_at": datetime_value(access_request.decided_at),
    }


def _approval_error_response(error: ApprovalActionError) -> JsonResponse:
    match error.kind:
        case "not_found":
            return _error_response(
                ErrorCode.NOT_FOUND,
                error.message,
                status=HTTPStatus.NOT_FOUND,
            )
        case "conflict":
            return _error_response(
                ErrorCode.SEMANTIC_VALIDATION_ERROR,
                error.message,
                error.details,
                status=HTTPStatus.CONFLICT,
            )
        case _:
            return _error_response(
                ErrorCode.VALIDATION_ERROR,
                error.message,
                error.details,
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )


def _invalid_payload_response(exc: ValidationError) -> JsonResponse:
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        "请求参数无效。",
        {"errors": str(exc)},
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def _method_not_allowed() -> JsonResponse:
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        "请求方法无效。",
        status=HTTPStatus.METHOD_NOT_ALLOWED,
    )
