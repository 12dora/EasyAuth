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
    AccessGrantRole,
)
from easyauth.portal.access_request_data import access_request_item, access_request_items_for_user
from easyauth.portal.permission_aggregation import (
    direct_permission_keys_by_grant_id,
    permission_keys,
    role_permission_keys_by_role_id,
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
    grant_ids = tuple(grant.id for grant in grants)
    role_keys, role_names, role_ids = _grant_roles_by_grant_id(grant_ids)
    direct_permissions = direct_permission_keys_by_grant_id(grant_ids)
    role_permissions = role_permission_keys_by_role_id(
        tuple(sorted({role_id for ids in role_ids.values() for role_id in ids})),
    )
    return tuple(
        _grant_item(
            grant,
            role_keys=role_keys.get(grant.id, ()),
            role_names=role_names.get(grant.id, ()),
            permission_keys=permission_keys(
                direct_permission_keys=direct_permissions.get(grant.id, set()),
                role_ids=role_ids.get(grant.id, ()),
                role_permission_keys_by_role_id=role_permissions,
            ),
        )
        for grant in grants
    )


def _grant_item(
    grant: AccessGrant,
    *,
    role_keys: tuple[str, ...],
    role_names: tuple[str, ...],
    permission_keys: tuple[str, ...],
) -> PortalJsonObject:
    return {
        "app_key": grant.app.app_key,
        "app_name": grant.app.name,
        "roles": _json_strings(role_keys),
        "role_names": _json_strings(role_names),
        "permissions": _json_strings(permission_keys),
        "version": grant.version,
        "grant_type": grant.grant_type,
        "grant_expires_at": datetime_value(grant.grant_expires_at),
    }


def _grant_roles_by_grant_id(
    grant_ids: tuple[int, ...],
) -> tuple[dict[int, tuple[str, ...]], dict[int, tuple[str, ...]], dict[int, tuple[int, ...]]]:
    role_keys: dict[int, list[str]] = {grant_id: [] for grant_id in grant_ids}
    role_names: dict[int, list[str]] = {grant_id: [] for grant_id in grant_ids}
    role_ids: dict[int, list[int]] = {grant_id: [] for grant_id in grant_ids}
    links = (
        AccessGrantRole.objects.select_related("role")
        .filter(grant_id__in=grant_ids, role__is_active=True)
        .order_by("grant_id", "role__key")
    )
    for link in links:
        role_keys.setdefault(link.grant_id, []).append(link.role.key)
        role_names.setdefault(link.grant_id, []).append(link.role.name)
        role_ids.setdefault(link.grant_id, []).append(link.role_id)
    return (
        {grant_id: tuple(keys) for grant_id, keys in role_keys.items()},
        {grant_id: tuple(names) for grant_id, names in role_names.items()},
        {grant_id: tuple(ids) for grant_id, ids in role_ids.items()},
    )


def _json_strings(values: tuple[str, ...]) -> list[JsonValue]:
    result: list[JsonValue] = []
    result.extend(values)
    return result
