from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from django.db.models import Q, QuerySet
from django.utils import timezone

from easyauth.applications.models import RolePermission
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    AccessGrant,
    AccessGrantPermission,
    AccessGrantRole,
)
from easyauth.grants.operations import parse_grant_type

if TYPE_CHECKING:
    from collections.abc import Sequence

    from easyauth.accounts.models import UserMirror

EXPIRING_SOON_DAYS: Final = 14
EMPTY_LABEL: Final = "-"


@dataclass(frozen=True, slots=True)
class PortalGrantRow:
    app_name: str
    grant_label: str
    role_names: str
    permission_keys: str
    version: int
    grant_expires_at: datetime | None
    is_expiring_soon: bool


def current_grant_rows_for_user(user: UserMirror) -> tuple[PortalGrantRow, ...]:
    current_time = timezone.now()
    grants = tuple(_current_visible_grants(user=user, current_time=current_time))
    return _grant_rows(grants, current_time=current_time)


def expiring_grant_rows(rows: Sequence[PortalGrantRow]) -> tuple[PortalGrantRow, ...]:
    return tuple(sorted((row for row in rows if row.is_expiring_soon), key=_expiring_sort_key))


def _current_visible_grants(
    *,
    user: UserMirror,
    current_time: datetime,
) -> QuerySet[AccessGrant]:
    return (
        AccessGrant.objects.select_related("app")
        .filter(
            user=user,
            app__is_active=True,
            is_current=True,
            status=GRANT_STATUS_ACTIVE,
        )
        .filter(
            Q(grant_type=GRANT_TYPE_PERMANENT)
            | Q(grant_type=GRANT_TYPE_TIMED, grant_expires_at__gt=current_time),
        )
        .order_by("app__app_key", "grant_expires_at", "id")
    )


def _grant_rows(
    grants: tuple[AccessGrant, ...],
    *,
    current_time: datetime,
) -> tuple[PortalGrantRow, ...]:
    grant_ids = tuple(grant.id for grant in grants)
    role_names_by_grant_id, role_ids_by_grant_id = _role_memberships_by_grant_id(grant_ids)
    direct_permission_keys_by_grant_id = _direct_permission_keys_by_grant_id(grant_ids)
    role_permission_keys_by_role_id = _role_permission_keys_by_role_id(
        tuple(
            sorted(
                {
                    role_id
                    for role_ids in role_ids_by_grant_id.values()
                    for role_id in role_ids
                },
            ),
        ),
    )
    return tuple(
        _grant_row(
            grant,
            role_names=role_names_by_grant_id.get(grant.id, ()),
            permission_keys=_permission_keys(
                direct_permission_keys=direct_permission_keys_by_grant_id.get(grant.id, set()),
                role_ids=role_ids_by_grant_id.get(grant.id, ()),
                role_permission_keys_by_role_id=role_permission_keys_by_role_id,
            ),
            current_time=current_time,
        )
        for grant in grants
    )


def _grant_row(
    grant: AccessGrant,
    *,
    role_names: tuple[str, ...],
    permission_keys: tuple[str, ...],
    current_time: datetime,
) -> PortalGrantRow:
    return PortalGrantRow(
        app_name=grant.app.name,
        grant_label=_grant_label(grant.grant_type),
        role_names=_label(role_names),
        permission_keys=_label(permission_keys),
        version=grant.version,
        grant_expires_at=grant.grant_expires_at,
        is_expiring_soon=_is_expiring_soon(grant, current_time=current_time),
    )


def _role_memberships_by_grant_id(
    grant_ids: tuple[int, ...],
) -> tuple[dict[int, tuple[str, ...]], dict[int, tuple[int, ...]]]:
    role_names: dict[int, list[str]] = {grant_id: [] for grant_id in grant_ids}
    role_ids: dict[int, list[int]] = {grant_id: [] for grant_id in grant_ids}
    links = (
        AccessGrantRole.objects.select_related("role")
        .filter(grant_id__in=grant_ids)
        .order_by("grant_id", "role__key")
    )
    for link in links:
        role_names.setdefault(link.grant_id, []).append(link.role.name)
        role_ids.setdefault(link.grant_id, []).append(link.role_id)
    return (
        {grant_id: tuple(names) for grant_id, names in role_names.items()},
        {grant_id: tuple(ids) for grant_id, ids in role_ids.items()},
    )


def _direct_permission_keys_by_grant_id(grant_ids: tuple[int, ...]) -> dict[int, set[str]]:
    permission_keys: dict[int, set[str]] = {grant_id: set() for grant_id in grant_ids}
    links = (
        AccessGrantPermission.objects.select_related("permission")
        .filter(grant_id__in=grant_ids)
        .order_by("grant_id", "permission__key")
    )
    for link in links:
        permission_keys.setdefault(link.grant_id, set()).add(link.permission.key)
    return permission_keys


def _role_permission_keys_by_role_id(role_ids: tuple[int, ...]) -> dict[int, set[str]]:
    permission_keys: dict[int, set[str]] = {role_id: set() for role_id in role_ids}
    links = (
        RolePermission.objects.select_related("permission")
        .filter(role_id__in=role_ids)
        .order_by("role_id", "permission__key")
    )
    for link in links:
        permission_keys.setdefault(link.role_id, set()).add(link.permission.key)
    return permission_keys


def _permission_keys(
    *,
    direct_permission_keys: set[str],
    role_ids: tuple[int, ...],
    role_permission_keys_by_role_id: dict[int, set[str]],
) -> tuple[str, ...]:
    permission_keys = set(direct_permission_keys)
    for role_id in role_ids:
        permission_keys.update(role_permission_keys_by_role_id.get(role_id, set()))
    return tuple(sorted(permission_keys))


def _is_expiring_soon(grant: AccessGrant, *, current_time: datetime) -> bool:
    grant_expires_at = grant.grant_expires_at
    if grant_expires_at is None:
        return False
    cutoff = current_time + timedelta(days=EXPIRING_SOON_DAYS)
    return current_time < grant_expires_at <= cutoff


def _grant_label(grant_type: str) -> str:
    match parse_grant_type(grant_type):
        case "permanent":
            return "长期"
        case "timed":
            return "限时"


def _label(values: tuple[str, ...]) -> str:
    if not values:
        return EMPTY_LABEL
    return "、".join(values)


def _expiring_sort_key(row: PortalGrantRow) -> tuple[datetime, str, int]:
    grant_expires_at = row.grant_expires_at
    if grant_expires_at is None:
        message = "即将过期授权必须包含过期时间。"
        raise TypeError(message)
    return (grant_expires_at, row.app_name, row.version)
