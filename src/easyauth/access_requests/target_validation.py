from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from easyauth.applications.models import ApprovalRule

if TYPE_CHECKING:
    from easyauth.applications.models import App, Permission, Role


@dataclass(frozen=True, slots=True)
class AccessRequestTargetValidationError(Exception):
    messages: tuple[str, ...]

    @override
    def __str__(self) -> str:
        return "; ".join(self.messages)


def validate_request_targets(
    app: App,
    roles: tuple[Role, ...],
    permissions: tuple[Permission, ...],
) -> None:
    errors = (*role_target_errors(app, roles), *permission_target_errors(app, permissions))
    if errors:
        raise AccessRequestTargetValidationError(errors)


def role_target_errors(app: App, roles: tuple[Role, ...]) -> tuple[str, ...]:
    errors: list[str] = []
    for role in roles:
        errors.extend(f"{role.key}: {message}" for message in _role_error_messages(app, role))
    return tuple(errors)


def permission_target_errors(app: App, permissions: tuple[Permission, ...]) -> tuple[str, ...]:
    errors: list[str] = []
    for permission in permissions:
        errors.extend(
            f"{permission.key}: {message}"
            for message in _permission_error_messages(app, permission)
        )
    return tuple(errors)


def _role_error_messages(app: App, role: Role) -> tuple[str, ...]:
    errors: list[str] = []
    if role.app != app:
        errors.append("Role must belong to the access request app.")
    if not role.requestable:
        errors.append("Role must be requestable.")
    if not role.is_active:
        errors.append("Role must be active.")
    if not ApprovalRule.objects.filter(app=app, role=role, is_active=True).exists():
        errors.append("Role must have an active approval rule.")
    return tuple(errors)


def _permission_error_messages(app: App, permission: Permission) -> tuple[str, ...]:
    errors: list[str] = []
    if permission.app != app:
        errors.append("Permission must belong to the access request app.")
    if not permission.is_active:
        errors.append("Permission must be active.")
    if permission.deprecated_at is not None:
        errors.append("Permission must not be deprecated.")
    if not ApprovalRule.objects.filter(app=app, permission=permission, is_active=True).exists():
        errors.append("Permission must have an active approval rule.")
    return tuple(errors)
