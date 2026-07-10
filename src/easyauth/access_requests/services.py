from __future__ import annotations

import hashlib
import json
from datetime import UTC
from typing import TYPE_CHECKING, final

from django.db import IntegrityError, transaction

from easyauth.access_requests.application import (
    AccessRequestApplication,
    AccessRequestApplicationError,
    apply_approved_access_request,
)
from easyauth.access_requests.models import (
    REQUEST_STATUS_SUBMITTED,
    REQUEST_TYPE_GRANT,
    AccessRequest,
    AccessRequestApprover,
    AccessRequestGroup,
    AccessRequestPermission,
)
from easyauth.access_requests.submission_types import (
    AccessRequestGrantType,
    AccessRequestIdempotencyConflictError,
    AccessRequestInput,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
    AccessRequestType,
    ScopedAccessRequestGrant,
)
from easyauth.access_requests.submission_validation import (
    ensure_managed_users_requests_have_approver,
    unique_authorization_groups,
    unique_direct_grants,
    validate_submission_scope,
    validated_approver_user_ids,
    validated_request_type,
)
from easyauth.accounts.models import UserMirror
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from easyauth.applications.models import AuthorizationGroup
    from easyauth.audit.models import JsonValue

IDEMPOTENCY_KEY_MAX_LENGTH = 128

__all__ = (
    "AccessRequestApplication",
    "AccessRequestApplicationError",
    "AccessRequestGrantType",
    "AccessRequestIdempotencyConflictError",
    "AccessRequestInput",
    "AccessRequestService",
    "AccessRequestSubmission",
    "AccessRequestSubmissionError",
    "AccessRequestType",
)


@final
class AccessRequestService:
    @staticmethod
    def submit_grant_request(input_data: AccessRequestSubmission) -> AccessRequest:
        return _submit_access_request(input_data, request_type=REQUEST_TYPE_GRANT)

    @staticmethod
    def submit_access_request(input_data: AccessRequestSubmission) -> AccessRequest:
        return _submit_access_request(input_data, request_type=input_data.request_type)

    @staticmethod
    def apply_approved_access_request(input_data: AccessRequestApplication) -> AccessRequest:
        return apply_approved_access_request(input_data)


def _submit_access_request(
    input_data: AccessRequestSubmission,
    *,
    request_type: str,
) -> AccessRequest:
    parsed_request_type = validated_request_type(request_type)
    authorization_groups = unique_authorization_groups(input_data.authorization_groups)
    direct_grants = unique_direct_grants(input_data.direct_grants)
    submitted_approver_user_ids = tuple(input_data.approver_user_ids)
    idempotency_key = _validated_idempotency_key(input_data.idempotency_key)
    payload_digest = _submission_payload_digest(
        input_data,
        request_type=parsed_request_type,
        authorization_groups=authorization_groups,
        direct_grants=direct_grants,
        approver_user_ids=submitted_approver_user_ids,
    )
    existing = _idempotent_request(input_data, idempotency_key, payload_digest)
    if existing is not None:
        return existing
    validate_submission_scope(input_data, parsed_request_type, authorization_groups, direct_grants)
    ensure_managed_users_requests_have_approver(
        authorization_groups=authorization_groups,
        direct_grants=direct_grants,
        approver_user_ids=submitted_approver_user_ids,
    )
    approver_user_ids = validated_approver_user_ids(
        submitted_approver_user_ids,
        applicant_user_id=input_data.user.authentik_user_id,
    )

    try:
        with transaction.atomic():
            existing = _locked_idempotent_request(
                input_data,
                idempotency_key,
                payload_digest,
            )
            if existing is not None:
                return existing
            access_request = AccessRequest(
                user=input_data.user,
                app=input_data.app,
                request_type=parsed_request_type,
                status=REQUEST_STATUS_SUBMITTED,
                grant_type=input_data.grant_type,
                grant_expires_at=input_data.grant_expires_at,
                reason=input_data.reason,
                idempotency_key=idempotency_key,
                payload_digest=payload_digest,
            )
            access_request.full_clean(validate_constraints=False)
            access_request.save()
            _create_approver_links(access_request, approver_user_ids)
            _create_group_links(access_request, authorization_groups)
            _create_direct_grant_links(access_request, direct_grants)
            _record_submitted_event(
                input_data,
                access_request,
                authorization_groups,
                direct_grants,
                approver_user_ids,
            )
            return access_request
    except IntegrityError:
        existing = _idempotent_request(input_data, idempotency_key, payload_digest)
        if existing is None:
            raise
        return existing


def _create_approver_links(
    access_request: AccessRequest,
    approver_user_ids: tuple[str, ...],
) -> None:
    approvers = UserMirror.objects.in_bulk(
        approver_user_ids,
        field_name="authentik_user_id",
    )
    if len(approvers) != len(approver_user_ids):
        message = "validated approver set changed before persistence"
        raise RuntimeError(message)
    _ = AccessRequestApprover.objects.bulk_create(
        AccessRequestApprover(
            access_request=access_request,
            approver=approvers[user_id],
        )
        for user_id in approver_user_ids
    )


def _validated_idempotency_key(value: str) -> str:
    if value == "" or value != value.strip() or len(value) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise AccessRequestSubmissionError(("invalid idempotency key",))
    return value


def _submission_payload_digest(
    input_data: AccessRequestSubmission,
    *,
    request_type: str,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
    approver_user_ids: tuple[str, ...],
) -> str:
    expires_at = input_data.grant_expires_at
    payload = {
        "app_key": input_data.app.app_key,
        "approver_user_ids": sorted(
            {user_id.strip() for user_id in approver_user_ids if user_id.strip()}
        ),
        "authorization_group_keys": sorted(group.key for group in authorization_groups),
        "direct_grants": sorted((grant.permission.key, grant.scope_key) for grant in direct_grants),
        "grant_expires_at": (
            None
            if expires_at is None
            else expires_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        ),
        "grant_type": input_data.grant_type,
        "reason": input_data.reason,
        "request_type": request_type,
        "user_id": input_data.user.authentik_user_id,
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _idempotent_request(
    input_data: AccessRequestSubmission,
    idempotency_key: str,
    payload_digest: str,
) -> AccessRequest | None:
    existing = AccessRequest.objects.filter(
        user=input_data.user,
        idempotency_key=idempotency_key,
    ).first()
    return _matching_idempotent_request(existing, payload_digest)


def _locked_idempotent_request(
    input_data: AccessRequestSubmission,
    idempotency_key: str,
    payload_digest: str,
) -> AccessRequest | None:
    existing = (
        AccessRequest.objects.select_for_update()
        .filter(user=input_data.user, idempotency_key=idempotency_key)
        .first()
    )
    return _matching_idempotent_request(existing, payload_digest)


def _matching_idempotent_request(
    existing: AccessRequest | None,
    payload_digest: str,
) -> AccessRequest | None:
    if existing is None:
        return None
    if existing.payload_digest != payload_digest:
        raise AccessRequestIdempotencyConflictError
    return existing


def _create_group_links(
    access_request: AccessRequest,
    authorization_groups: tuple[AuthorizationGroup, ...],
) -> None:
    for group in authorization_groups:
        link = AccessRequestGroup(access_request=access_request, authorization_group=group)
        link.full_clean()
        link.save()


def _create_direct_grant_links(
    access_request: AccessRequest,
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> None:
    for direct_grant in direct_grants:
        link = AccessRequestPermission(
            access_request=access_request,
            permission=direct_grant.permission,
            scope_key=direct_grant.scope_key,
        )
        link.full_clean()
        link.save()


def _record_submitted_event(
    input_data: AccessRequestSubmission,
    access_request: AccessRequest,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
    approver_user_ids: tuple[str, ...],
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type=input_data.actor_type,
            actor_id=input_data.actor_id,
            action="access_request_submitted",
            target_type="access_request",
            target_id=_request_target_id(access_request),
            metadata=_audit_metadata(
                input_data,
                access_request,
                authorization_groups,
                direct_grants,
                approver_user_ids,
            ),
        ),
    )


def _audit_metadata(
    input_data: AccessRequestSubmission,
    access_request: AccessRequest,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
    approver_user_ids: tuple[str, ...],
) -> dict[str, JsonValue]:
    authorization_group_keys: list[JsonValue] = [group.key for group in authorization_groups]
    direct_grant_items: list[JsonValue] = [
        {"permission": direct_grant.permission.key, "scope": direct_grant.scope_key}
        for direct_grant in direct_grants
    ]
    approver_user_id_items: list[JsonValue] = list(approver_user_ids)
    return {
        "user_id": input_data.user.authentik_user_id,
        "app_key": input_data.app.app_key,
        "request_type": access_request.request_type,
        "grant_type": input_data.grant_type,
        "authorization_group_keys": authorization_group_keys,
        "direct_grants": direct_grant_items,
        "approver_user_ids": approver_user_id_items,
        "reason": input_data.reason,
    }


def _request_target_id(access_request: AccessRequest) -> str:
    return (
        f"{access_request.user.authentik_user_id}:{access_request.app.app_key}:{access_request.id}"
    )
