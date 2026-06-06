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
    AccessRequestPermission,
    AccessRequestRole,
)
from easyauth.access_requests.submission_types import (
    AccessRequestGrantType,
    AccessRequestInput,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
    AccessRequestType,
)
from easyauth.access_requests.submission_validation import (
    unique_permissions,
    unique_roles,
    validate_submission_scope,
    validated_request_type,
)
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from easyauth.applications.models import Permission, Role
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
    roles = unique_roles(input_data.roles)
    permissions = unique_permissions(input_data.permissions)
    validate_submission_scope(input_data, parsed_request_type, roles, permissions)

    with transaction.atomic():
        access_request = AccessRequest(
            user=input_data.user,
            app=input_data.app,
            request_type=parsed_request_type,
            status=REQUEST_STATUS_SUBMITTED,
            grant_type=input_data.grant_type,
            grant_expires_at=input_data.grant_expires_at,
            reason=input_data.reason,
        )
        access_request.full_clean()
        access_request.save()
        _create_role_links(access_request, roles)
        _create_permission_links(access_request, permissions)
        _record_submitted_event(input_data, access_request, roles, permissions)
        return access_request


def _create_role_links(access_request: AccessRequest, roles: tuple[Role, ...]) -> None:
    for role in roles:
        link = AccessRequestRole(access_request=access_request, role=role)
        link.full_clean()
        link.save()


def _create_permission_links(
    access_request: AccessRequest,
    permissions: tuple[Permission, ...],
) -> None:
    for permission in permissions:
        link = AccessRequestPermission(access_request=access_request, permission=permission)
        link.full_clean()
        link.save()


def _record_submitted_event(
    input_data: AccessRequestSubmission,
    access_request: AccessRequest,
    roles: tuple[Role, ...],
    permissions: tuple[Permission, ...],
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type=input_data.actor_type,
            actor_id=input_data.actor_id,
            action="access_request_submitted",
            target_type="access_request",
            target_id=_request_target_id(access_request),
            metadata=_audit_metadata(input_data, access_request, roles, permissions),
        ),
    )


def _audit_metadata(
    input_data: AccessRequestSubmission,
    access_request: AccessRequest,
    roles: tuple[Role, ...],
    permissions: tuple[Permission, ...],
) -> dict[str, JsonValue]:
    role_keys: list[JsonValue] = [role.key for role in roles]
    permission_keys: list[JsonValue] = [permission.key for permission in permissions]
    return {
        "user_id": input_data.user.authentik_user_id,
        "app_key": input_data.app.app_key,
        "request_type": access_request.request_type,
        "grant_type": input_data.grant_type,
        "roles": role_keys,
        "role_keys": role_keys,
        "permissions": permission_keys,
        "permission_keys": permission_keys,
        "reason": input_data.reason,
    }


def _request_target_id(access_request: AccessRequest) -> str:
    return (
        f"{access_request.user.authentik_user_id}:"
        f"{access_request.app.app_key}:"
        f"{access_request.id}"
    )
