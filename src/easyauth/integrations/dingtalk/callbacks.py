from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar, Literal

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.access_requests.models import (
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_REJECTED,
    AccessRequest,
)
from easyauth.access_requests.services import (
    AccessRequestApplication,
    AccessRequestApplicationError,
    AccessRequestService,
)
from easyauth.api.errors import ErrorCode, ErrorResponse, JsonValue, build_error_response
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.integrations.dingtalk.signature import is_valid_callback_signature

type CallbackResult = AccessRequest | JsonResponse


class _DingTalkCallbackPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    process_instance_id: str = Field(min_length=1, max_length=128)
    status: Literal["approved", "rejected"]


@csrf_exempt
@require_POST
def dingtalk_callback(request: HttpRequest) -> JsonResponse:
    body = request.body
    if not _request_signature_is_valid(request, body):
        _record_security_event(
            event_type="dingtalk_callback_signature_rejected",
            target_id="unknown",
            metadata={"reason": "invalid_signature"},
        )
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "DingTalk 回调签名无效。",
            status=HTTPStatus.FORBIDDEN,
        )
    try:
        payload = _DingTalkCallbackPayload.model_validate_json(body)
    except ValidationError as exc:
        _record_security_event(
            event_type="dingtalk_callback_payload_rejected",
            target_id="unknown",
            metadata={"errors": str(exc)},
        )
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "DingTalk 回调参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    match _process_callback(payload):
        case AccessRequest() as access_request:
            return _json_response(_success_payload(access_request))
        case JsonResponse() as response:
            return response


def _request_signature_is_valid(request: HttpRequest, body: bytes) -> bool:
    secret = str(getattr(settings, "EASYAUTH_DINGTALK_CALLBACK_SECRET", ""))
    timestamp = request.headers.get("X-EasyAuth-DingTalk-Timestamp", "")
    signature = request.headers.get("X-EasyAuth-DingTalk-Signature", "")
    return is_valid_callback_signature(
        secret=secret,
        timestamp=timestamp,
        body=body,
        signature=signature,
    )


def _process_callback(payload: _DingTalkCallbackPayload) -> CallbackResult:
    match payload.status:
        case "approved":
            return _approve_request(payload.process_instance_id)
        case "rejected":
            return _reject_request(payload.process_instance_id)


def _approve_request(process_instance_id: str) -> CallbackResult:
    match _mark_approved(process_instance_id):
        case AccessRequest() as access_request:
            pass
        case JsonResponse() as response:
            return response
    try:
        return AccessRequestService.apply_approved_access_request(
            AccessRequestApplication(
                request_id=access_request.id,
                actor_type="dingtalk",
                actor_id=process_instance_id,
                reason="DingTalk approval callback",
            ),
        )
    except AccessRequestApplicationError as exc:
        return _error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            str(exc),
            {"process_instance_id": process_instance_id},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


@transaction.atomic
def _mark_approved(process_instance_id: str) -> CallbackResult:
    access_request = _locked_request(process_instance_id)
    if access_request is None:
        return _unknown_process_response(process_instance_id)
    match access_request.status:
        case "submitted":
            access_request.status = REQUEST_STATUS_APPROVED
            access_request.approved_at = timezone.now()
            access_request.full_clean()
            access_request.save(update_fields=["status", "approved_at"])
            _record_request_event(
                access_request=access_request,
                action="dingtalk_approval_approved",
                process_instance_id=process_instance_id,
            )
            return access_request
        case "approved" | "grant_applied":
            return access_request
        case status:
            return _error_response(
                ErrorCode.SEMANTIC_VALIDATION_ERROR,
                "DingTalk 回调状态与申请状态不匹配。",
                {"process_instance_id": process_instance_id, "status": status},
                status=HTTPStatus.CONFLICT,
            )


@transaction.atomic
def _reject_request(process_instance_id: str) -> CallbackResult:
    access_request = _locked_request(process_instance_id)
    if access_request is None:
        return _unknown_process_response(process_instance_id)
    match access_request.status:
        case "approved" | "grant_applied" | "grant_failed" | "rejected":
            return access_request
        case "submitted":
            access_request.status = REQUEST_STATUS_REJECTED
            access_request.full_clean()
            access_request.save(update_fields=["status"])
            _record_request_event(
                access_request=access_request,
                action="dingtalk_approval_rejected",
                process_instance_id=process_instance_id,
            )
            return access_request
        case status:
            return _error_response(
                ErrorCode.SEMANTIC_VALIDATION_ERROR,
                "DingTalk 回调状态与申请状态不匹配。",
                {"process_instance_id": process_instance_id, "status": status},
                status=HTTPStatus.CONFLICT,
            )


def _locked_request(process_instance_id: str) -> AccessRequest | None:
    return (
        AccessRequest.objects.select_for_update()
        .select_related("user", "app")
        .filter(dingtalk_process_instance_id=process_instance_id)
        .first()
    )


def _unknown_process_response(process_instance_id: str) -> JsonResponse:
    _record_security_event(
        event_type="dingtalk_callback_unknown_process",
        target_id=process_instance_id,
        metadata={"process_instance_id": process_instance_id},
    )
    return _error_response(
        ErrorCode.NOT_FOUND,
        "DingTalk 审批实例不存在。",
        {"process_instance_id": process_instance_id},
        status=HTTPStatus.NOT_FOUND,
    )


def _success_payload(access_request: AccessRequest) -> dict[str, JsonValue]:
    return {
        "request_id": access_request.id,
        "process_instance_id": access_request.dingtalk_process_instance_id or "",
        "status": access_request.status,
    }


def _record_request_event(
    *,
    access_request: AccessRequest,
    action: str,
    process_instance_id: str,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="dingtalk",
            actor_id=process_instance_id,
            action=action,
            target_type="access_request",
            target_id=str(access_request.id),
            metadata={
                "process_instance_id": process_instance_id,
                "user_id": access_request.user.authentik_user_id,
                "app_key": access_request.app.app_key,
            },
        ),
    )


def _record_security_event(
    *,
    event_type: str,
    target_id: str,
    metadata: dict[str, JsonValue],
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="dingtalk",
            actor_id="callback",
            action=event_type,
            target_type="dingtalk_callback",
            target_id=target_id,
            metadata=metadata,
        ),
    )


def _error_response(
    code: ErrorCode,
    message: str,
    details: dict[str, JsonValue] | None = None,
    *,
    status: int,
) -> JsonResponse:
    return _json_response(build_error_response(code, message, details), status=status)


def _json_response(
    payload: dict[str, JsonValue] | ErrorResponse,
    *,
    status: int = HTTPStatus.OK,
) -> JsonResponse:
    return JsonResponse(
        payload,
        status=status,
        json_dumps_params={"ensure_ascii": False},
    )
