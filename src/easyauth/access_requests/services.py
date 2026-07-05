from __future__ import annotations

from typing import TYPE_CHECKING, final

from django.db import transaction

from easyauth.access_requests.application import (
    AccessRequestApplication,
    AccessRequestApplicationError,
    apply_approved_access_request,
)
from easyauth.access_requests.models import (
    REQUEST_STATUS_SUBMITTED,
    REQUEST_TYPE_GRANT,
    AccessRequest,
    AccessRequestGroup,
    AccessRequestPermission,
)
from easyauth.access_requests.submission_types import (
    AccessRequestGrantType,
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
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from easyauth.applications.models import AuthorizationGroup
    from easyauth.audit.models import JsonValue

__all__ = (
    "AccessRequestApplication",
    "AccessRequestApplicationError",
    "AccessRequestGrantType",
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
    validate_submission_scope(input_data, parsed_request_type, authorization_groups, direct_grants)
    ensure_managed_users_requests_have_approver(
        authorization_groups=authorization_groups,
        direct_grants=direct_grants,
        approver_user_ids=input_data.approver_user_ids,
    )
    approver_user_ids = validated_approver_user_ids(
        input_data.approver_user_ids,
        applicant_user_id=input_data.user.authentik_user_id,
    )

    with transaction.atomic():
        access_request = AccessRequest(
            user=input_data.user,
            app=input_data.app,
            request_type=parsed_request_type,
            status=REQUEST_STATUS_SUBMITTED,
            grant_type=input_data.grant_type,
            grant_expires_at=input_data.grant_expires_at,
            reason=input_data.reason,
            approver_user_ids=list(approver_user_ids),
        )
        access_request.full_clean()
        access_request.save()
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
        f"{access_request.user.authentik_user_id}:"
        f"{access_request.app.app_key}:"
        f"{access_request.id}"
    )
