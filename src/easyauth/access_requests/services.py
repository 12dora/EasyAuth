from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, final, override

from django.db import transaction

from easyauth.access_requests.models import (
    REQUEST_STATUS_SUBMITTED,
    REQUEST_TYPE_GRANT,
    AccessRequest,
    AccessRequestRole,
)
from easyauth.applications.models import ApprovalRule
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from easyauth.accounts.models import UserMirror
    from easyauth.applications.models import App, Role
    from easyauth.audit.models import JsonValue

type AccessRequestGrantType = Literal["permanent", "timed"]


@dataclass(frozen=True, slots=True)
class AccessRequestSubmissionError(Exception):
    messages: tuple[str, ...]

    @override
    def __str__(self) -> str:
        return "; ".join(self.messages)


@dataclass(frozen=True, slots=True)
class AccessRequestSubmission:
    user: UserMirror
    app: App
    roles: Iterable[Role]
    grant_type: AccessRequestGrantType
    grant_expires_at: datetime | None
    reason: str
    actor_type: str
    actor_id: str


AccessRequestInput = AccessRequestSubmission


@final
class AccessRequestService:
    @staticmethod
    def submit_grant_request(input_data: AccessRequestSubmission) -> AccessRequest:
        roles = _unique_roles(input_data.roles)
        _validate_expiration_shape(input_data)
        _validate_app(input_data.app)
        _validate_roles(input_data.app, roles)

        with transaction.atomic():
            access_request = AccessRequest(
                user=input_data.user,
                app=input_data.app,
                request_type=REQUEST_TYPE_GRANT,
                status=REQUEST_STATUS_SUBMITTED,
                grant_type=input_data.grant_type,
                grant_expires_at=input_data.grant_expires_at,
                reason=input_data.reason,
            )
            access_request.full_clean()
            access_request.save()
            _create_role_links(access_request, roles)
            _record_submitted_event(input_data, access_request, roles)
            return access_request


def _validate_expiration_shape(input_data: AccessRequestSubmission) -> None:
    match input_data.grant_type:
        case "permanent":
            if input_data.grant_expires_at is not None:
                raise AccessRequestSubmissionError(
                    ("Permanent requests must not include an expiration",),
                )
        case "timed":
            if input_data.grant_expires_at is None:
                raise AccessRequestSubmissionError(
                    ("Timed requests must include an expiration",),
                )


def _unique_roles(roles: Iterable[Role]) -> tuple[Role, ...]:
    role_by_id: dict[int, Role] = {}
    for role in roles:
        role_by_id[role.id] = role
    return tuple(role_by_id.values())


def _validate_app(app: App) -> None:
    if not app.is_active:
        raise AccessRequestSubmissionError(("app is not active",))


def _validate_roles(app: App, roles: tuple[Role, ...]) -> None:
    if not roles:
        raise AccessRequestSubmissionError(("at least one role is required",))

    errors: list[str] = []
    for role in roles:
        role_errors = _role_errors(app, role)
        errors.extend(f"{role.key}: {message}" for message in role_errors)

    if errors:
        raise AccessRequestSubmissionError(tuple(errors))


def _role_errors(app: App, role: Role) -> list[str]:
    errors: list[str] = []
    if role.app != app:
        errors.append("Role must belong to the access request app.")
    if not role.requestable:
        errors.append("Role must be requestable.")
    if not role.is_active:
        errors.append("Role must be active.")
    if not _has_active_approval_rule(app, role):
        errors.append("Role must have an active approval rule.")
    return errors


def _has_active_approval_rule(app: App, role: Role) -> bool:
    return ApprovalRule.objects.filter(app=app, role=role, is_active=True).exists()


def _create_role_links(access_request: AccessRequest, roles: tuple[Role, ...]) -> None:
    for role in roles:
        link = AccessRequestRole(access_request=access_request, role=role)
        link.full_clean()
        link.save()


def _record_submitted_event(
    input_data: AccessRequestSubmission,
    access_request: AccessRequest,
    roles: tuple[Role, ...],
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type=input_data.actor_type,
            actor_id=input_data.actor_id,
            action="access_request_submitted",
            target_type="access_request",
            target_id=_request_target_id(access_request),
            metadata=_audit_metadata(input_data, roles),
        ),
    )


def _audit_metadata(
    input_data: AccessRequestSubmission,
    roles: tuple[Role, ...],
) -> dict[str, JsonValue]:
    role_keys: list[JsonValue] = [role.key for role in roles]
    return {
        "user_id": input_data.user.authentik_user_id,
        "app_key": input_data.app.app_key,
        "grant_type": input_data.grant_type,
        "roles": role_keys,
        "role_keys": role_keys,
        "reason": input_data.reason,
    }


def _request_target_id(access_request: AccessRequest) -> str:
    return (
        f"{access_request.user.authentik_user_id}:"
        f"{access_request.app.app_key}:"
        f"{access_request.id}"
    )
