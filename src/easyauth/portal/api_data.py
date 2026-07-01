from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from django.db.models import Q, QuerySet
from django.utils import timezone

from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import JsonValue
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    AccessGrant,
)
from easyauth.grants.query import resolve_user_permissions
from easyauth.portal.access_request_data import access_request_item, access_request_items_for_user
from easyauth.portal.permission_aggregation import (
    json_expanded_grants,
    json_groups,
)

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror

DEFAULT_EXPIRING_DAYS: Final = 14
__all__: Final = (
    "access_request_item",
    "access_request_items_for_user",
    "current_grant_items_for_user",
    "expiring_grant_items_for_user",
)

type PortalJsonObject = dict[str, JsonValue]


def current_grant_items_for_user(user: UserMirror) -> tuple[PortalJsonObject, ...]:
    current_time = timezone.now()
    grants = tuple(_current_visible_grants(user=user, current_time=current_time))
    return _grant_items(grants)


def expiring_grant_items_for_user(
    user: UserMirror,
    *,
    days: int = DEFAULT_EXPIRING_DAYS,
) -> tuple[PortalJsonObject, ...]:
    current_time = timezone.now()
    cutoff = current_time + timedelta(days=days)
    grants = tuple(
        _current_visible_grants(user=user, current_time=current_time)
        .filter(grant_type=GRANT_TYPE_TIMED, grant_expires_at__lte=cutoff)
        .order_by("grant_expires_at", "app__app_key", "id"),
    )
    return _grant_items(grants)


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


def _grant_items(grants: tuple[AccessGrant, ...]) -> tuple[PortalJsonObject, ...]:
    return tuple(_grant_item(grant) for grant in grants)


def _grant_item(grant: AccessGrant) -> PortalJsonObject:
    snapshot = resolve_user_permissions(user=grant.user, app=grant.app)
    return {
        "app_key": grant.app.app_key,
        "app_name": grant.app.name,
        "groups": json_groups(snapshot.groups),
        "grants": json_expanded_grants(snapshot.grants),
        "grant_version": snapshot.grant_version,
        "catalog_version": snapshot.catalog_version,
        "snapshot_version": snapshot.snapshot_version,
        "grant_type": grant.grant_type,
        "grant_expires_at": datetime_value(grant.grant_expires_at),
    }
