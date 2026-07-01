from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from easyauth.accounts.models import UserMirror
from easyauth.accounts.status import parse_user_status
from easyauth.applications.models import App, RolePermission
from easyauth.grants.models import (
    AccessGrant,
    AccessGrantPermission,
    AccessGrantRole,
)
from easyauth.grants.status import parse_grant_status

if TYPE_CHECKING:
    from datetime import datetime

type UserSelector = UserMirror | str


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

    latest_grant = _latest_grant(resolved_user, app)
    version = 0 if latest_grant is None else latest_grant.version
    if latest_grant is None or not _grant_has_effective_permissions(resolved_user, latest_grant):
        return _empty_snapshot(user_id=user_id, app=app, version=version)
    return _grant_snapshot(user_id=user_id, app=app, grant=latest_grant, version=version)


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


def _latest_grant(user: UserMirror, app: App) -> AccessGrant | None:
    return (
        AccessGrant.objects.filter(user=user, app=app)
        .order_by("-version", "-id")
        .first()
    )


def _grant_has_effective_permissions(user: UserMirror, grant: AccessGrant) -> bool:
    match parse_user_status(user.status):
        case "active":
            pass
        case "disabled" | "departed":
            return False

    if not grant.is_current:
        return False

    match parse_grant_status(grant.status):
        case "active":
            return True
        case "revoked" | "expired":
            return False


def _grant_snapshot(
    *,
    user_id: str,
    app: App,
    grant: AccessGrant,
    version: int,
) -> PermissionSnapshot:
    direct_permission_keys = _direct_permission_keys(grant)
    role_permission_keys = _role_permission_keys(grant)
    return PermissionSnapshot(
        user_id=user_id,
        app_key=app.app_key,
        version=version,
        roles=_role_keys(grant),
        permissions=tuple(sorted(direct_permission_keys | role_permission_keys)),
        grant_expires_at=grant.grant_expires_at,
    )


def _role_keys(grant: AccessGrant) -> tuple[str, ...]:
    return tuple(
        link.role.key
        for link in AccessGrantRole.objects.select_related("role")
        .filter(grant=grant, role__is_active=True)
        .order_by("role__key")
    )


def _direct_permission_keys(grant: AccessGrant) -> set[str]:
    return {
        link.permission.key
        for link in AccessGrantPermission.objects.select_related("permission").filter(
            grant=grant,
            permission__is_active=True,
            permission__deprecated_at__isnull=True,
        )
    }


def _role_permission_keys(grant: AccessGrant) -> set[str]:
    return {
        link.permission.key
        for link in RolePermission.objects.select_related("permission").filter(
            role__access_grant_roles__grant=grant,
            role__is_active=True,
            permission__is_active=True,
            permission__deprecated_at__isnull=True,
        )
    }


def _empty_snapshot(*, user_id: str, app: App, version: int) -> PermissionSnapshot:
    return PermissionSnapshot(
        user_id=user_id,
        app_key=app.app_key,
        version=version,
        roles=(),
        permissions=(),
    )
