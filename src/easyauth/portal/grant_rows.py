from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from django.db.models import Q, QuerySet
from django.utils import timezone

from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    AccessGrant,
)
from easyauth.grants.operations import parse_grant_type
from easyauth.grants.query import resolve_user_permissions

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
    return tuple(
        _grant_row(
            grant,
            current_time=current_time,
        )
        for grant in grants
    )


def _grant_row(
    grant: AccessGrant,
    *,
    current_time: datetime,
) -> PortalGrantRow:
    snapshot = resolve_user_permissions(user=grant.user, app=grant.app)
    return PortalGrantRow(
        app_name=grant.app.name,
        grant_label=_grant_label(grant.grant_type),
        role_names=_label(tuple(group.name for group in snapshot.groups)),
        permission_keys=_label(
            tuple(f"{item.permission}:{item.scope}" for item in snapshot.grants),
        ),
        version=grant.version,
        grant_expires_at=grant.grant_expires_at,
        is_expiring_soon=_is_expiring_soon(grant, current_time=current_time),
    )


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
