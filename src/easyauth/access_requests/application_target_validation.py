from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.applications.models import ApprovalRule

if TYPE_CHECKING:
    from easyauth.access_requests.submission_types import AccessRequestType
    from easyauth.applications.models import App, Permission, Role


def apply_target_errors(
    app: App,
    request_type: AccessRequestType,
    roles: tuple[Role, ...],
    permissions: tuple[Permission, ...],
) -> tuple[str, ...]:
    match request_type:
        case "grant" | "change" | "revoke" | "renew":
            return (*_role_errors(app, roles), *_permission_errors(app, permissions))


def _role_errors(app: App, roles: tuple[Role, ...]) -> tuple[str, ...]:
    errors: list[str] = []
    for role in roles:
        if role.app != app:
            errors.append(f"{role.key}: Role must belong to the access request app.")
        if not role.requestable:
            errors.append(f"{role.key}: Role must be requestable.")
        if not role.is_active:
            errors.append(f"{role.key}: Role must be active.")
        if _role_rule_is_stale(app, role):
            errors.append(f"{role.key}: Role must have an active approval rule.")
    return tuple(errors)


def _permission_errors(app: App, permissions: tuple[Permission, ...]) -> tuple[str, ...]:
    errors: list[str] = []
    for permission in permissions:
        if permission.app != app:
            errors.append(f"{permission.key}: Permission must belong to the access request app.")
        if not permission.is_active:
            errors.append(f"{permission.key}: Permission must be active.")
        if permission.deprecated_at is not None:
            errors.append(f"{permission.key}: Permission must not be deprecated.")
        if _permission_rule_is_stale(app, permission):
            errors.append(f"{permission.key}: Permission must have an active approval rule.")
    return tuple(errors)


def _role_rule_is_stale(app: App, role: Role) -> bool:
    return not ApprovalRule.objects.filter(app=app, role=role, is_active=True).exists()


def _permission_rule_is_stale(app: App, permission: Permission) -> bool:
    return not ApprovalRule.objects.filter(
        app=app,
        permission=permission,
        is_active=True,
    ).exists()
