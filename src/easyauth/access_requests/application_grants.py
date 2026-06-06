from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol, override

from django.utils import timezone

from easyauth.access_requests.application_target_validation import apply_target_errors
from easyauth.access_requests.high_risk_duration import high_risk_duration_error
from easyauth.access_requests.models import (
    AccessRequest,
    AccessRequestPermission,
    AccessRequestRole,
)
from easyauth.access_requests.submission_validation import validated_request_type
from easyauth.applications.models import RolePermission
from easyauth.grants.models import AccessGrantPermission, AccessGrantRole
from easyauth.grants.operations import current_grant
from easyauth.grants.services import GrantMutationInput, GrantService

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.applications.models import Permission, Role
    from easyauth.grants.models import AccessGrant

type ApplicationGrantType = Literal["permanent", "timed"]

CURRENT_GRANT_REQUIRED_MESSAGE: Final = "current active grant is required"
TARGET_CONFIGURATION_REQUIRED_MESSAGE: Final = "target configuration is no longer valid"


@dataclass(frozen=True, slots=True)
class GrantApplyFailureError(Exception):
    message: str

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class _GrantLifecycle:
    grant_type: ApplicationGrantType
    grant_expires_at: datetime | None


class _GrantApplicationInput(Protocol):
    @property
    def actor_type(self) -> str: ...

    @property
    def actor_id(self) -> str: ...

    @property
    def reason(self) -> str: ...


def apply_grant_fact(
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
) -> AccessGrant:
    _validate_request_scope(access_request)
    roles = _selected_roles(access_request)
    permissions = _selected_permissions(access_request)
    request_type = validated_request_type(access_request.request_type)
    if apply_target_errors(access_request.app, request_type, roles, permissions):
        raise GrantApplyFailureError(TARGET_CONFIGURATION_REQUIRED_MESSAGE)
    match request_type:
        case "grant":
            return GrantService.create_grant(
                _grant_mutation_input(
                    access_request,
                    input_data,
                    roles,
                    permissions,
                    _request_grant_lifecycle(access_request),
                ),
            )
        case "change":
            _ = _active_current_grant(access_request)
            return GrantService.change_grant(
                _grant_mutation_input(
                    access_request,
                    input_data,
                    roles,
                    permissions,
                    _request_grant_lifecycle(access_request),
                ),
            )
        case "renew":
            current = _active_current_grant(access_request)
            _validate_renew_target(current, roles, permissions, access_request.grant_expires_at)
            duration_error = high_risk_duration_error(roles, access_request.grant_expires_at)
            if duration_error:
                raise GrantApplyFailureError(duration_error)
            return GrantService.change_grant(
                _grant_mutation_input(
                    access_request,
                    input_data,
                    roles,
                    permissions,
                    _request_grant_lifecycle(access_request),
                ),
            )
        case "revoke":
            return _apply_revoke_request(access_request, input_data, roles, permissions)


def _validate_request_scope(access_request: AccessRequest) -> None:
    match access_request.user.status:
        case "active":
            pass
        case _:
            raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    if not access_request.app.is_active:
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)


def _apply_revoke_request(
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
    roles: tuple[Role, ...],
    permissions: tuple[Permission, ...],
) -> AccessGrant:
    current = _active_current_grant(access_request)
    if roles or permissions:
        _validate_revoke_target(current, roles, permissions)
        return GrantService.change_grant(
            _grant_mutation_input(
                access_request,
                input_data,
                roles,
                permissions,
                _current_grant_lifecycle(access_request),
            ),
        )
    revoked = GrantService.revoke_grant(
        user=access_request.user,
        app=access_request.app,
        actor_type=input_data.actor_type,
        actor_id=input_data.actor_id,
        reason=input_data.reason,
    )
    if revoked is None:
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    return revoked


def _request_grant_lifecycle(access_request: AccessRequest) -> _GrantLifecycle:
    return _GrantLifecycle(
        grant_type=_grant_type(access_request.grant_type),
        grant_expires_at=access_request.grant_expires_at,
    )


def _current_grant_lifecycle(access_request: AccessRequest) -> _GrantLifecycle:
    grant = _active_current_grant(access_request)
    return _GrantLifecycle(
        grant_type=_grant_type(grant.grant_type),
        grant_expires_at=grant.grant_expires_at,
    )


def _active_current_grant(access_request: AccessRequest) -> AccessGrant:
    grant = current_grant(access_request.user, access_request.app)
    if grant is None:
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    match grant.status:
        case "active":
            pass
        case _:
            raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    match grant.grant_type:
        case "permanent":
            return grant
        case "timed":
            expires_at = grant.grant_expires_at
            if expires_at is None or expires_at <= timezone.now():
                raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
            return grant
        case _:
            raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)


def _validate_revoke_target(
    current: AccessGrant,
    roles: tuple[Role, ...],
    permissions: tuple[Permission, ...],
) -> None:
    current_role_ids = _current_role_ids(current)
    target_role_ids = {role.id for role in roles}
    if not target_role_ids.issubset(current_role_ids):
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    current_permission_ids = _current_permission_ids(current)
    target_permission_ids = {permission.id for permission in permissions}
    if not target_permission_ids.issubset(current_permission_ids):
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    if (
        target_role_ids == current_role_ids
        and _target_permission_ids(roles, permissions) == current_permission_ids
    ):
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)


def _validate_renew_target(
    current: AccessGrant,
    roles: tuple[Role, ...],
    permissions: tuple[Permission, ...],
    requested_expires_at: datetime | None,
) -> None:
    if {role.id for role in roles} != _current_role_ids(current):
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    if _target_permission_ids(roles, permissions) != _current_permission_ids(current):
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    current_expires_at = current.grant_expires_at
    if current_expires_at is None or requested_expires_at is None:
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)
    if requested_expires_at <= current_expires_at:
        raise GrantApplyFailureError(CURRENT_GRANT_REQUIRED_MESSAGE)


def _current_role_ids(grant: AccessGrant) -> set[int]:
    return set(AccessGrantRole.objects.filter(grant=grant).values_list("role_id", flat=True))


def _current_permission_ids(grant: AccessGrant) -> set[int]:
    direct_ids = set(
        AccessGrantPermission.objects.filter(grant=grant).values_list("permission_id", flat=True),
    )
    role_ids = AccessGrantRole.objects.filter(grant=grant).values_list("role_id", flat=True)
    role_permission_ids = set(
        RolePermission.objects.filter(role_id__in=role_ids).values_list("permission_id", flat=True),
    )
    return direct_ids | role_permission_ids


def _target_permission_ids(
    roles: tuple[Role, ...],
    permissions: tuple[Permission, ...],
) -> set[int]:
    role_ids = tuple(role.id for role in roles)
    role_permission_ids = set(
        RolePermission.objects.filter(role_id__in=role_ids).values_list("permission_id", flat=True),
    )
    return role_permission_ids | {permission.id for permission in permissions}


def _grant_mutation_input(
    access_request: AccessRequest,
    input_data: _GrantApplicationInput,
    roles: tuple[Role, ...],
    permissions: tuple[Permission, ...],
    lifecycle: _GrantLifecycle,
) -> GrantMutationInput:
    return GrantMutationInput(
        user=access_request.user,
        app=access_request.app,
        grant_type=lifecycle.grant_type,
        grant_expires_at=lifecycle.grant_expires_at,
        roles=roles,
        permissions=permissions,
        actor_type=input_data.actor_type,
        actor_id=input_data.actor_id,
    )


def _selected_roles(access_request: AccessRequest) -> tuple[Role, ...]:
    return tuple(
        link.role
        for link in AccessRequestRole.objects.select_related("role").filter(
            access_request=access_request,
        )
    )


def _selected_permissions(access_request: AccessRequest) -> tuple[Permission, ...]:
    return tuple(
        link.permission
        for link in AccessRequestPermission.objects.select_related("permission").filter(
            access_request=access_request,
        )
    )


def _grant_type(value: str) -> ApplicationGrantType:
    match value:
        case "permanent":
            return "permanent"
        case "timed":
            return "timed"
        case unsupported:
            message = f"unsupported grant type: {unsupported}"
            raise GrantApplyFailureError(message)
