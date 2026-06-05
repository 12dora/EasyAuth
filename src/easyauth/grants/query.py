from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from django.core.exceptions import ValidationError

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, RolePermission
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    GRANT_STATUS_EXPIRED,
    GRANT_STATUS_REVOKED,
    AccessGrant,
    AccessGrantPermission,
    AccessGrantRole,
)

if TYPE_CHECKING:
    from datetime import datetime

type UserSelector = UserMirror | str
type UserStatus = Literal["active", "disabled", "departed"]
type GrantStatus = Literal["active", "revoked", "expired"]


@dataclass(frozen=True, slots=True)
class PermissionSnapshot:
    user_id: str
    app_key: str
    version: int
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    grant_expires_at: datetime | None = None


def resolve_user_permissions(*, user: UserSelector, app: App) -> PermissionSnapshot:
    resolved_user = _resolve_user(user)
    user_id = _user_id(user)
    if resolved_user is None:
        return _empty_snapshot(user_id=user_id, app=app, version=0)

    latest_grant = (
        AccessGrant.objects.filter(user=resolved_user, app=app)
        .order_by("-version", "-id")
        .first()
    )
    version = 0 if latest_grant is None else latest_grant.version

    if latest_grant is None:
        return _empty_snapshot(user_id=user_id, app=app, version=version)

    match _parse_user_status(resolved_user.status):
        case "active":
            pass
        case "disabled" | "departed":
            return _empty_snapshot(user_id=user_id, app=app, version=version)

    if not latest_grant.is_current:
        return _empty_snapshot(user_id=user_id, app=app, version=version)

    match _parse_grant_status(latest_grant.status):
        case "active":
            pass
        case "revoked" | "expired":
            return _empty_snapshot(user_id=user_id, app=app, version=version)

    roles = tuple(
        link.role.key
        for link in AccessGrantRole.objects.select_related("role")
        .filter(grant=latest_grant)
        .order_by("role__key")
    )
    direct_permission_keys = {
        link.permission.key
        for link in AccessGrantPermission.objects.select_related("permission").filter(
            grant=latest_grant,
        )
    }
    role_permission_keys = {
        link.permission.key
        for link in RolePermission.objects.select_related("permission").filter(
            role__access_grant_roles__grant=latest_grant,
        )
    }
    return PermissionSnapshot(
        user_id=user_id,
        app_key=app.app_key,
        version=version,
        roles=roles,
        permissions=tuple(sorted(direct_permission_keys | role_permission_keys)),
        grant_expires_at=latest_grant.grant_expires_at,
    )


def _resolve_user(user: UserSelector) -> UserMirror | None:
    match user:
        case UserMirror() as user_model:
            return user_model
        case str() as user_id:
            return UserMirror.objects.filter(authentik_user_id=user_id).first()


def _user_id(user: UserSelector) -> str:
    match user:
        case UserMirror() as user_model:
            return user_model.authentik_user_id
        case str() as user_id:
            return user_id


def _parse_user_status(status: str) -> UserStatus:
    match status:
        case "active":
            return "active"
        case "disabled":
            return "disabled"
        case "departed":
            return "departed"
        case unsupported:
            raise ValidationError({"status": f"Unsupported user status: {unsupported}"})


def _parse_grant_status(status: str) -> GrantStatus:
    match status:
        case "active":
            return GRANT_STATUS_ACTIVE
        case "revoked":
            return GRANT_STATUS_REVOKED
        case "expired":
            return GRANT_STATUS_EXPIRED
        case unsupported:
            raise ValidationError({"status": f"Unsupported grant status: {unsupported}"})


def _empty_snapshot(*, user_id: str, app: App, version: int) -> PermissionSnapshot:
    return PermissionSnapshot(
        user_id=user_id,
        app_key=app.app_key,
        version=version,
        roles=(),
        permissions=(),
    )
