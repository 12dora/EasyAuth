from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils import timezone

from easyauth.access_requests.high_risk_duration import high_risk_duration_error
from easyauth.access_requests.submission_types import (
    AccessRequestGrantType,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
    AccessRequestType,
)
from easyauth.applications.models import ApprovalRule, RolePermission
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE as GRANT_RECORD_STATUS_ACTIVE,
)
from easyauth.grants.models import (
    AccessGrant,
    AccessGrantPermission,
    AccessGrantRole,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from easyauth.accounts.models import UserMirror
    from easyauth.applications.models import App, Permission, Role


def validated_request_type(request_type: str) -> AccessRequestType:
    match request_type:
        case "grant" | "change" | "revoke" | "renew":
            return request_type
        case _:
            raise AccessRequestSubmissionError(("unsupported request type",))


def unique_roles(roles: Iterable[Role]) -> tuple[Role, ...]:
    role_by_id: dict[int, Role] = {}
    for role in roles:
        role_by_id[role.id] = role
    return tuple(role_by_id.values())


def unique_permissions(permissions: Iterable[Permission]) -> tuple[Permission, ...]:
    permission_by_id: dict[int, Permission] = {}
    for permission in permissions:
        permission_by_id[permission.id] = permission
    return tuple(permission_by_id.values())


def validate_submission_scope(
    input_data: AccessRequestSubmission,
    request_type: AccessRequestType,
    roles: tuple[Role, ...],
    permissions: tuple[Permission, ...],
) -> None:
    _validate_user(input_data.user)
    _validate_expiration_shape(input_data.grant_type, input_data.grant_expires_at)
    _validate_app(input_data.app)

    match request_type:
        case "grant":
            _validate_roles(input_data.app, roles)
            _validate_no_permissions_for_grant(permissions)
        case "change":
            _ = _active_lifecycle_grant(input_data.user, input_data.app)
            _validate_targets_present(roles, permissions)
            if roles:
                _validate_roles(input_data.app, roles)
            _validate_permissions(input_data.app, permissions)
        case "revoke":
            grant = _active_lifecycle_grant(input_data.user, input_data.app)
            _validate_targets_belong_to_app(input_data.app, roles, permissions)
            _validate_revoke_subset(grant, roles, permissions)
        case "renew":
            grant = _active_lifecycle_grant(input_data.user, input_data.app)
            _validate_renew_request(input_data.grant_type, input_data.grant_expires_at, grant)
            _validate_targets_belong_to_app(input_data.app, roles, permissions)
            _validate_renew_targets(grant, roles, permissions)
            duration_error = high_risk_duration_error(roles, input_data.grant_expires_at)
            if duration_error:
                raise AccessRequestSubmissionError((duration_error,))


def _validate_user(user: UserMirror) -> None:
    match user.status:
        case "active":
            return
        case _:
            raise AccessRequestSubmissionError(("user is not active",))


def _validate_expiration_shape(
    grant_type: AccessRequestGrantType,
    grant_expires_at: datetime | None,
) -> None:
    match grant_type:
        case "permanent":
            if grant_expires_at is not None:
                raise AccessRequestSubmissionError(
                    ("Permanent requests must not include an expiration",),
                )
        case "timed":
            if grant_expires_at is None:
                raise AccessRequestSubmissionError(
                    ("Timed requests must include an expiration",),
                )


def _validate_app(app: App) -> None:
    if not app.is_active:
        raise AccessRequestSubmissionError(("app is not active",))


def _validate_no_permissions_for_grant(permissions: tuple[Permission, ...]) -> None:
    if permissions:
        raise AccessRequestSubmissionError(("grant requests do not accept direct permissions",))


def _validate_targets_present(
    roles: tuple[Role, ...],
    permissions: tuple[Permission, ...],
) -> None:
    if not roles and not permissions:
        raise AccessRequestSubmissionError(("at least one role or permission is required",))


def _active_lifecycle_grant(user: UserMirror, app: App) -> AccessGrant:
    grant = AccessGrant.objects.filter(
        user=user,
        app=app,
        is_current=True,
        status=GRANT_RECORD_STATUS_ACTIVE,
    ).first()
    if grant is None:
        raise AccessRequestSubmissionError(("active grant is required",))
    match grant.grant_type:
        case "timed":
            expires_at = grant.grant_expires_at
            if expires_at is None or expires_at <= timezone.now():
                raise AccessRequestSubmissionError(("active grant is required",))
        case "permanent":
            pass
        case _:
            raise AccessRequestSubmissionError(("active grant is required",))
    return grant


def _validate_renew_request(
    grant_type: AccessRequestGrantType,
    grant_expires_at: datetime | None,
    grant: AccessGrant,
) -> None:
    match grant.grant_type:
        case "timed":
            pass
        case "permanent":
            raise AccessRequestSubmissionError(("renew requires a timed grant",))
        case _:
            raise AccessRequestSubmissionError(("renew requires a timed grant",))

    match grant_type:
        case "timed":
            current_expiration = grant.grant_expires_at
            if grant_expires_at is None or current_expiration is None:
                raise AccessRequestSubmissionError(("renew requires a timed grant expiration",))
            if grant_expires_at <= current_expiration:
                raise AccessRequestSubmissionError(("renew expiration must extend current grant",))
        case "permanent":
            raise AccessRequestSubmissionError(("renew requires a timed grant",))


def _validate_revoke_subset(
    grant: AccessGrant,
    roles: tuple[Role, ...],
    permissions: tuple[Permission, ...],
) -> None:
    current_role_ids = set(
        AccessGrantRole.objects.filter(grant=grant).values_list("role_id", flat=True),
    )
    target_role_ids = {role.id for role in roles}
    if not target_role_ids.issubset(current_role_ids):
        raise AccessRequestSubmissionError(("target roles must be subset of current grant",))

    current_permission_ids = _current_permission_ids(grant)
    target_permission_ids = {permission.id for permission in permissions}
    if not target_permission_ids.issubset(current_permission_ids):
        raise AccessRequestSubmissionError(("target permissions must be subset of current grant",))
    target_effective_permission_ids = _target_permission_ids(roles, permissions)
    if (
        target_role_ids == current_role_ids
        and target_effective_permission_ids == current_permission_ids
    ):
        raise AccessRequestSubmissionError(("revoke request must reduce current grant",))


def _validate_renew_targets(
    grant: AccessGrant,
    roles: tuple[Role, ...],
    permissions: tuple[Permission, ...],
) -> None:
    current_role_ids = set(
        AccessGrantRole.objects.filter(grant=grant).values_list("role_id", flat=True),
    )
    if {role.id for role in roles} != current_role_ids:
        raise AccessRequestSubmissionError(("renew request must keep current roles",))
    if _target_permission_ids(roles, permissions) != _current_permission_ids(grant):
        raise AccessRequestSubmissionError(("renew request must keep current permissions",))


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


def _validate_targets_belong_to_app(
    app: App,
    roles: tuple[Role, ...],
    permissions: tuple[Permission, ...],
) -> None:
    errors: list[str] = []
    errors.extend(
        f"{role.key}: Role must belong to the access request app."
        for role in roles
        if role.app != app
    )
    errors.extend(
        f"{permission.key}: Permission must belong to the access request app."
        for permission in permissions
        if permission.app != app
    )
    if errors:
        raise AccessRequestSubmissionError(tuple(errors))


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
    if not ApprovalRule.objects.filter(app=app, role=role, is_active=True).exists():
        errors.append("Role must have an active approval rule.")
    return errors


def _validate_permissions(app: App, permissions: tuple[Permission, ...]) -> None:
    errors: list[str] = []
    for permission in permissions:
        permission_errors = _permission_errors(app, permission)
        errors.extend(f"{permission.key}: {message}" for message in permission_errors)

    if errors:
        raise AccessRequestSubmissionError(tuple(errors))


def _permission_errors(app: App, permission: Permission) -> list[str]:
    errors: list[str] = []
    if permission.app != app:
        errors.append("Permission must belong to the access request app.")
    if not permission.is_active:
        errors.append("Permission must be active.")
    if not ApprovalRule.objects.filter(app=app, permission=permission, is_active=True).exists():
        errors.append("Permission must have an active approval rule.")
    return errors
