from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Literal, cast

from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.access_requests.inbound_callbacks import (
    ApprovalCallbackError,
    apply_approval_callback,
)
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.responses import error_response as _error_response
from easyauth.api.responses import json_response as _json_response
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.integrations.dingtalk.signature import is_valid_callback_signature

if TYPE_CHECKING:
    from django.http import HttpRequest, JsonResponse

    from easyauth.access_requests.models import AccessRequest


class _DingTalkCallbackPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    process_instance_id: str = Field(min_length=1, max_length=128)
    status: Literal["approved", "rejected"]
    # 实际执行审批操作的人; 审计必须记录最终审批人, 且要与申请的审批人列表核对。
    approver_user_id: str = Field(min_length=1, max_length=128)


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
            metadata=_payload_rejected_metadata(body, exc),
        )
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "DingTalk 回调参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    try:
        access_request = apply_approval_callback(
            process_instance_id=payload.process_instance_id,
            status=payload.status,
            approver_user_id=payload.approver_user_id,
            raw_payload=body,
        )
    except ApprovalCallbackError as exc:
        if exc.kind == "approver_rejected":
            _record_security_event(
                event_type="dingtalk_callback_approver_rejected",
                target_id=payload.process_instance_id,
                metadata=dict(exc.details),
            )
        return _callback_error_response(exc)
    return _json_response(_success_payload(access_request))


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


def _callback_error_response(exc: ApprovalCallbackError) -> JsonResponse:
    match exc.kind:
        case "not_found":
            return _error_response(
                ErrorCode.NOT_FOUND,
                exc.message,
                exc.details,
                status=HTTPStatus.NOT_FOUND,
            )
        case "conflict":
            return _error_response(
                ErrorCode.SEMANTIC_VALIDATION_ERROR,
                exc.message,
                exc.details,
                status=HTTPStatus.CONFLICT,
            )
        case "approver_rejected":
            return _error_response(
                ErrorCode.PERMISSION_DENIED,
                exc.message,
                exc.details,
                status=HTTPStatus.FORBIDDEN,
            )
        case "application_error" | "validation_error":
            return _error_response(
                ErrorCode.SEMANTIC_VALIDATION_ERROR,
                exc.message,
                exc.details,
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )


def _success_payload(access_request: AccessRequest) -> dict[str, JsonValue]:
    return {
        "request_id": access_request.id,
        "process_instance_id": access_request.dingtalk_process_instance_id or "",
        "status": access_request.status,
    }


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


def _payload_rejected_metadata(body: bytes, exc: ValidationError) -> dict[str, JsonValue]:
    metadata: dict[str, JsonValue] = {"errors": str(exc)}
    summary = _payload_summary(body)
    if summary:
        metadata["payload_summary"] = summary
    return metadata


def _payload_summary(body: bytes) -> dict[str, JsonValue]:
    try:
        loaded = cast("object", json.loads(body.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    payload = cast("dict[object, object]", loaded)

    summary: dict[str, JsonValue] = {}
    process_instance_id = payload.get("process_instance_id")
    if isinstance(process_instance_id, str):
        summary["process_instance_id"] = process_instance_id
    status = payload.get("status")
    if isinstance(status, str):
        summary["status"] = status
    return summary
