from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, override

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from easyauth.access_requests.application_grants import (
    GrantApplyFailureError,
    GrantBaseRevisionConflictError,
    apply_grant_fact,
)
from easyauth.access_requests.models import (
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_GRANT_CONFLICT,
    REQUEST_STATUS_GRANT_EXPIRED,
    REQUEST_STATUS_GRANT_FAILED,
    AccessRequest,
    AccessRequestGroupGrantSnapshot,
)
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.services import GrantMutationExpiredError

if TYPE_CHECKING:
    from easyauth.audit.models import JsonValue
    from easyauth.grants.models import AccessGrant

APPLY_FAILED_MESSAGE: Final = "grant apply failed"
APPLY_EXPIRED_MESSAGE: Final = "grant expired before apply"
APPLY_BASE_CONFLICT_MESSAGE: Final = "base grant revision conflict"
REQUEST_NOT_FOUND_MESSAGE: Final = "access request is not found"

type AccessRequestApplicationErrorKind = Literal[
    "apply_failed",
    "base_revision_conflict",
    "not_found",
    "request_expired",
    "status_conflict",
]


@dataclass(frozen=True, slots=True)
class AccessRequestApplication:
    request_id: int
    actor_type: str
    actor_id: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class AccessRequestApplicationError(Exception):
    message: str
    kind: AccessRequestApplicationErrorKind = "apply_failed"

    @override
    def __str__(self) -> str:
        return self.message


def apply_approved_access_request(input_data: AccessRequestApplication) -> AccessRequest:
    try:
        with transaction.atomic():
            access_request = _applicable_access_request(input_data.request_id)
            match access_request.status:
                case "grant_applied":
                    return access_request
                case "approved":
                    pass
                case status:
                    message = f"access request must be approved before grant apply: {status}"
                    raise AccessRequestApplicationError(message)
            grant = apply_grant_fact(access_request, input_data)
            _mark_grant_applied(access_request)
            _record_applied_event(access_request, input_data, grant)
            return access_request
    except GrantMutationExpiredError as exc:
        _mark_grant_expired(input_data, error=str(exc))
        raise AccessRequestApplicationError(APPLY_EXPIRED_MESSAGE, kind="request_expired") from exc
    except GrantBaseRevisionConflictError as exc:
        _mark_grant_conflict(input_data, error=str(exc))
        raise AccessRequestApplicationError(
            APPLY_BASE_CONFLICT_MESSAGE,
            kind="base_revision_conflict",
        ) from exc
    except (DjangoValidationError, IntegrityError, GrantApplyFailureError) as exc:
        _mark_grant_failed(input_data, error=str(exc))
        raise AccessRequestApplicationError(APPLY_FAILED_MESSAGE) from exc


def _approved_access_request(request_id: int) -> AccessRequest:
    access_request = _locked_access_request(request_id)
    match access_request.status:
        case "approved":
            return access_request
        case status:
            message = f"access request must be approved before grant apply: {status}"
            raise AccessRequestApplicationError(message, kind="status_conflict")


def _applicable_access_request(request_id: int) -> AccessRequest:
    access_request = _locked_access_request(request_id)
    match access_request.status:
        case "approved" | "grant_applied":
            return access_request
        case status:
            message = f"access request must be approved before grant apply: {status}"
            raise AccessRequestApplicationError(message, kind="status_conflict")


def _locked_access_request(request_id: int) -> AccessRequest:
    access_request = (
        AccessRequest.objects.select_for_update()
        .select_related("user", "app")
        .filter(id=request_id)
        .first()
    )
    if access_request is None:
        raise AccessRequestApplicationError(REQUEST_NOT_FOUND_MESSAGE, kind="not_found")
    return access_request


def _mark_grant_applied(access_request: AccessRequest) -> None:
    access_request.status = REQUEST_STATUS_GRANT_APPLIED
    access_request.applied_at = timezone.now()
    access_request.full_clean()
    access_request.save(update_fields=["status", "applied_at"])


def _mark_grant_failed(
    input_data: AccessRequestApplication,
    *,
    error: str,
) -> None:
    with transaction.atomic():
        access_request = _approved_access_request(input_data.request_id)
        access_request.status = REQUEST_STATUS_GRANT_FAILED
        access_request.applied_at = None
        access_request.full_clean()
        access_request.save(update_fields=["status"])
        _ = AuditService.record(
            AuditRecord(
                actor_type=input_data.actor_type,
                actor_id=input_data.actor_id,
                action="grant_apply_failed",
                target_type="access_request",
                target_id=str(access_request.id),
                metadata=_request_metadata(access_request, error=error),
            ),
        )


def _mark_grant_conflict(
    input_data: AccessRequestApplication,
    *,
    error: str,
) -> None:
    with transaction.atomic():
        access_request = _approved_access_request(input_data.request_id)
        access_request.status = REQUEST_STATUS_GRANT_CONFLICT
        access_request.applied_at = None
        access_request.full_clean()
        access_request.save(update_fields=["status"])
        _ = AuditService.record(
            AuditRecord(
                actor_type=input_data.actor_type,
                actor_id=input_data.actor_id,
                action="grant_apply_conflict",
                target_type="access_request",
                target_id=str(access_request.id),
                metadata=_request_metadata(access_request, error=error),
            ),
        )


def _mark_grant_expired(
    input_data: AccessRequestApplication,
    *,
    error: str,
) -> None:
    with transaction.atomic():
        access_request = _approved_access_request(input_data.request_id)
        access_request.status = REQUEST_STATUS_GRANT_EXPIRED
        access_request.applied_at = None
        access_request.full_clean()
        access_request.save(update_fields=["status"])
        _ = AuditService.record(
            AuditRecord(
                actor_type=input_data.actor_type,
                actor_id=input_data.actor_id,
                action="grant_expired_before_apply",
                target_type="access_request",
                target_id=str(access_request.id),
                metadata=_request_metadata(access_request, error=error),
            ),
        )


def _record_applied_event(
    access_request: AccessRequest,
    input_data: AccessRequestApplication,
    grant: AccessGrant,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type=input_data.actor_type,
            actor_id=input_data.actor_id,
            action="access_request_grant_applied",
            target_type="access_request",
            target_id=str(access_request.id),
            metadata=_request_metadata(access_request, grant=grant),
        ),
    )


def _request_metadata(
    access_request: AccessRequest,
    *,
    grant: AccessGrant | None = None,
    error: str = "",
) -> dict[str, JsonValue]:
    metadata: dict[str, JsonValue] = {
        "user_id": access_request.user.authentik_user_id,
        "app_key": access_request.app.app_key,
        "request_type": access_request.request_type,
        "base_grant_id": access_request.base_grant_id,
        "base_grant_revision": access_request.base_grant_revision,
        "authorization_group_grants": _group_grant_snapshot_items(access_request),
    }
    if grant is not None:
        metadata["grant_id"] = grant.id
        metadata["version"] = grant.version
    if error != "":
        metadata["error"] = error
    return metadata


def _group_grant_snapshot_items(access_request: AccessRequest) -> list[JsonValue]:
    return [
        {
            "authorization_group_id_snapshot": snapshot.authorization_group_id_snapshot,
            "authorization_group_key": snapshot.authorization_group_key,
            "authorization_group_kind": snapshot.authorization_group_kind,
            "authorization_group_name": snapshot.authorization_group_name,
            "permission": snapshot.permission_key,
            "permission_name": snapshot.permission_name,
            "scope": snapshot.scope_key,
        }
        for snapshot in AccessRequestGroupGrantSnapshot.objects.filter(
            access_request=access_request,
        ).order_by("authorization_group_id_snapshot", "permission_key", "scope_key")
    ]
