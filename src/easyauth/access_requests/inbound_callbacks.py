from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, override

from django.db import transaction
from django.utils import timezone

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
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from easyauth.audit.models import JsonValue

type ApprovalCallbackStatus = Literal["approved", "rejected"]
type ApprovalCallbackErrorKind = Literal[
    "application_error",
    "conflict",
    "not_found",
    "validation_error",
]


@dataclass(frozen=True, slots=True)
class ApprovalCallbackError(Exception):
    kind: ApprovalCallbackErrorKind
    message: str
    details: dict[str, JsonValue]

    @override
    def __str__(self) -> str:
        return self.message


def apply_approval_callback(
    process_instance_id: str,
    status: str,
    actor_id: str,
    raw_payload: bytes,
) -> AccessRequest:
    _ = raw_payload
    match status:
        case "approved":
            return _approve_request(process_instance_id, actor_id)
        case "rejected":
            return _reject_request(process_instance_id)
        case _:
            raise ApprovalCallbackError(
                kind="validation_error",
                message="审批回调状态无效。",
                details={"process_instance_id": process_instance_id, "status": status},
            )


def _approve_request(process_instance_id: str, actor_id: str) -> AccessRequest:
    access_request = _mark_approved(process_instance_id)
    try:
        return AccessRequestService.apply_approved_access_request(
            AccessRequestApplication(
                request_id=access_request.id,
                actor_type="dingtalk",
                actor_id=actor_id,
                reason="DingTalk approval callback",
            ),
        )
    except AccessRequestApplicationError as exc:
        raise ApprovalCallbackError(
            kind="application_error",
            message=str(exc),
            details={"process_instance_id": process_instance_id},
        ) from exc


def _mark_approved(process_instance_id: str) -> AccessRequest:
    with transaction.atomic():
        access_request = _locked_request(process_instance_id)
        if access_request is not None:
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
                    raise _status_conflict_error(process_instance_id, status)
    raise _unknown_process_error(process_instance_id)


def _reject_request(process_instance_id: str) -> AccessRequest:
    with transaction.atomic():
        access_request = _locked_request(process_instance_id)
        if access_request is not None:
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
                    raise _status_conflict_error(process_instance_id, status)
    raise _unknown_process_error(process_instance_id)


def _locked_request(process_instance_id: str) -> AccessRequest | None:
    return (
        AccessRequest.objects.select_for_update()
        .select_related("user", "app")
        .filter(dingtalk_process_instance_id=process_instance_id)
        .first()
    )


def _unknown_process_error(process_instance_id: str) -> ApprovalCallbackError:
    _record_security_event(
        event_type="dingtalk_callback_unknown_process",
        target_id=process_instance_id,
        metadata={"process_instance_id": process_instance_id},
    )
    return ApprovalCallbackError(
        kind="not_found",
        message="DingTalk 审批实例不存在。",
        details={"process_instance_id": process_instance_id},
    )


def _status_conflict_error(process_instance_id: str, status: str) -> ApprovalCallbackError:
    return ApprovalCallbackError(
        kind="conflict",
        message="DingTalk 回调状态与申请状态不匹配。",
        details={"process_instance_id": process_instance_id, "status": status},
    )


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
