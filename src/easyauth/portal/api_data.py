from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from django.db.models import Q, QuerySet
from django.utils import timezone

from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import JsonValue
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    AccessGrant,
)
from easyauth.grants.query import PermissionSnapshot, resolve_user_permissions
from easyauth.portal.access_request_data import (
    access_request_item,
    access_request_items_for_user,
    access_request_page_for_user,
)
from easyauth.portal.pagination import PortalPage, build_page, page_request
from easyauth.portal.permission_aggregation import (
    json_expanded_grants,
    json_groups,
)

if TYPE_CHECKING:
    from django.http import QueryDict

    from easyauth.accounts.models import UserMirror
    from easyauth.grants.managed_users import ManagedUsersDirectoryCache

DEFAULT_EXPIRING_DAYS: Final = 14
__all__: Final = (
    "access_request_item",
    "access_request_items_for_user",
    "access_request_page_for_user",
    "current_grant_items_for_user",
    "current_grant_page_for_user",
    "expiring_grant_items_for_user",
    "expiring_grant_page_for_user",
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
    grants = tuple(_expiring_visible_grants(user=user, current_time=current_time, days=days))
    return _grant_items(grants)


def current_grant_page_for_user(user: UserMirror, query: QueryDict) -> PortalPage:
    # 先按页切 queryset 再解析权限, page_size 上限才能真正约束单次请求的工作量。
    current_time = timezone.now()
    return _grant_page(_current_visible_grants(user=user, current_time=current_time), query)


def expiring_grant_page_for_user(
    user: UserMirror,
    query: QueryDict,
    *,
    days: int = DEFAULT_EXPIRING_DAYS,
) -> PortalPage:
    current_time = timezone.now()
    return _grant_page(
        _expiring_visible_grants(user=user, current_time=current_time, days=days),
        query,
    )


def _grant_page(queryset: QuerySet[AccessGrant], query: QueryDict) -> PortalPage:
    request = page_request(query)
    total_items = queryset.count()
    grants = tuple(queryset[request.start : request.stop])
    return build_page(_grant_items(grants), request=request, total_items=total_items)


def _expiring_visible_grants(
    *,
    user: UserMirror,
    current_time: datetime,
    days: int,
) -> QuerySet[AccessGrant]:
    cutoff = current_time + timedelta(days=days)
    return (
        _current_visible_grants(user=user, current_time=current_time)
        .filter(
            Q(
                grant_groups__expires_at__gt=current_time,
                grant_groups__expires_at__lte=cutoff,
            )
            | Q(
                grant_permissions__expires_at__gt=current_time,
                grant_permissions__expires_at__lte=cutoff,
            ),
        )
        .distinct()
        .order_by("app__app_key", "id")
    )


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
            Q(grant_groups__expires_at__isnull=True)
            | Q(grant_groups__expires_at__gt=current_time)
            | Q(grant_permissions__expires_at__isnull=True)
            | Q(grant_permissions__expires_at__gt=current_time),
        )
        .distinct()
        .order_by("app__app_key", "id")
    )


def _grant_items(grants: tuple[AccessGrant, ...]) -> tuple[PortalJsonObject, ...]:
    # 整页 grant 共享同一份目录缓存, MANAGED_USERS 解析最多发一次 HTTP。
    directory_cache: ManagedUsersDirectoryCache = {}
    return tuple(_grant_item(grant, directory_cache) for grant in grants)


def _grant_item(
    grant: AccessGrant,
    directory_cache: ManagedUsersDirectoryCache,
) -> PortalJsonObject:
    snapshot = resolve_user_permissions(
        user=grant.user,
        app=grant.app,
        managed_users_cache=directory_cache,
    )
    grant_type, grant_expires_at = _grant_lifecycle_summary(snapshot)
    return {
        "app_key": grant.app.app_key,
        "app_name": grant.app.name,
        "groups": json_groups(snapshot.groups),
        "grants": json_expanded_grants(snapshot.grants),
        "grant_version": snapshot.grant_version,
        "catalog_version": snapshot.catalog_version,
        "snapshot_version": snapshot.snapshot_version,
        "grant_type": grant_type,
        "grant_expires_at": datetime_value(grant_expires_at),
    }


def _grant_lifecycle_summary(snapshot: PermissionSnapshot) -> tuple[str, datetime | None]:
    expirations = tuple(item.expires_at for item in (*snapshot.groups, *snapshot.grants))
    timed_expirations = tuple(expiration for expiration in expirations if expiration is not None)
    if not timed_expirations:
        return "permanent", None
    if len(timed_expirations) == len(expirations):
        return "timed", min(timed_expirations)
    return "mixed", min(timed_expirations)
