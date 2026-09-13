from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final

from django.db.models import Prefetch, Q, QuerySet
from django.http import HttpRequest, JsonResponse
from django.utils import timezone

from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import JsonValue
from easyauth.api.ordering import apply_ordering
from easyauth.api.ordering_expressions import GRANT_ORDERING_ANNOTATIONS
from easyauth.grants.grant_row_items import authorization_group_items, direct_grant_items
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from easyauth.grants.permission_aggregation import grant_lifecycle_summary
from easyauth.grants.query import expansion_catalog_for_grants, resolve_user_permissions
from easyauth.portal.access_request_data import (
    access_request_item,
    access_request_page_for_user,
)
from easyauth.portal.pagination import PortalPage, build_page, page_request
from easyauth.portal.permission_aggregation import (
    json_expanded_grants,
    json_groups,
)

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror
    from easyauth.grants.managed_users import ManagedUsersDirectoryCache
    from easyauth.grants.query import GrantExpansionCatalog

PORTAL_GRANT_ORDERING: Final[dict[str, str]] = {
    "app_key": "app__app_key",
    "expires_at": "ordering_expires_at",
    "created_at": "created_at",
    "groups": "ordering_group",
    "permission_details": "ordering_permission_count",
}
PORTAL_GRANT_DEFAULT_ORDER: Final[tuple[str, ...]] = ("app__app_key", "id")

DEFAULT_EXPIRING_DAYS: Final = 14
__all__: Final = (
    "access_request_item",
    "access_request_page_for_user",
    "current_grant_items_for_user",
    "current_grant_page_for_user",
    "expiring_grant_page_for_user",
)

type PortalJsonObject = dict[str, JsonValue]


def current_grant_items_for_user(user: UserMirror) -> tuple[PortalJsonObject, ...]:
    current_time = timezone.now()
    grants = tuple(_current_visible_grants(user=user, current_time=current_time))
    return _grant_items(grants)


def current_grant_page_for_user(
    user: UserMirror,
    request: HttpRequest,
) -> PortalPage | JsonResponse:
    # 先按页切 queryset 再解析权限, page_size 上限才能真正约束单次请求的工作量。
    current_time = timezone.now()
    return _grant_page(
        _current_visible_grants(user=user, current_time=current_time),
        request,
    )


def expiring_grant_page_for_user(
    user: UserMirror,
    request: HttpRequest,
    *,
    days: int = DEFAULT_EXPIRING_DAYS,
) -> PortalPage | JsonResponse:
    current_time = timezone.now()
    return _grant_page(
        _expiring_visible_grants(user=user, current_time=current_time, days=days),
        request,
    )


def _grant_page(
    queryset: QuerySet[AccessGrant],
    request: HttpRequest,
) -> PortalPage | JsonResponse:
    queryset = apply_ordering(
        request,
        queryset,
        PORTAL_GRANT_ORDERING,
        PORTAL_GRANT_DEFAULT_ORDER,
        annotations=GRANT_ORDERING_ANNOTATIONS,
    )
    if isinstance(queryset, JsonResponse):
        return queryset
    page = page_request(request.GET)
    total_items = queryset.count()
    grants = tuple(queryset[page.start : page.stop])
    return build_page(_grant_items(grants), request=page, total_items=total_items)


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
        .prefetch_related(
            Prefetch(
                "grant_groups",
                queryset=AccessGrantGroup.objects.select_related("authorization_group"),
            ),
            Prefetch(
                "grant_permissions",
                queryset=AccessGrantPermission.objects.select_related("permission"),
            ),
            "app__scopes",
        )
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
    catalog = expansion_catalog_for_grants(grants)
    return tuple(_grant_item(grant, directory_cache, catalog) for grant in grants)


def _grant_item(
    grant: AccessGrant,
    directory_cache: ManagedUsersDirectoryCache,
    catalog: GrantExpansionCatalog,
) -> PortalJsonObject:
    snapshot = resolve_user_permissions(
        user=grant.user,
        app=grant.app,
        managed_users_cache=directory_cache,
    )
    grant_type, grant_expires_at = grant_lifecycle_summary(snapshot)
    return {
        "grant_id": grant.id,
        "grant_revision": grant.version,
        "app_key": grant.app.app_key,
        "app_name": grant.app.name,
        "app_alias": grant.app.alias,
        "groups": json_groups(snapshot.groups),
        "grants": json_expanded_grants(snapshot.grants),
        "grant_version": snapshot.grant_version,
        "catalog_version": snapshot.catalog_version,
        "snapshot_version": snapshot.snapshot_version,
        "grant_type": grant_type,
        "grant_expires_at": datetime_value(grant_expires_at),
        "authorization_groups": authorization_group_items(grant),
        "direct_grants": direct_grant_items(grant, catalog),
    }
