from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from django.db.models import Prefetch, QuerySet

from easyauth.accounts.department_paths import department_path_labels
from easyauth.api.datetime_json import datetime_value
from easyauth.applications.models import AuthorizationGroupGrant
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission
from easyauth.grants.permission_aggregation import grant_lifecycle_summary
from easyauth.grants.query import (
    GrantExpansionCatalog,
    expansion_catalog_for_grants,
    snapshot_for_grant,
)
from easyauth.portal.permission_aggregation import json_expanded_grants, json_groups

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from easyauth.api.errors import JsonValue
    from easyauth.grants.managed_users import ManagedUsersDirectoryCache

__all__: Final = (
    "access_grant_row_queryset",
    "serialize_access_grant_row",
    "serialize_access_grant_rows",
)


def access_grant_row_queryset() -> QuerySet[AccessGrant]:
    return AccessGrant.objects.select_related("user", "app").prefetch_related(
        Prefetch(
            "grant_groups",
            queryset=AccessGrantGroup.objects.select_related(
                "authorization_group",
            ).prefetch_related(
                Prefetch(
                    "authorization_group__grants",
                    queryset=AuthorizationGroupGrant.objects.select_related("permission"),
                ),
            ),
        ),
        Prefetch(
            "grant_permissions",
            queryset=AccessGrantPermission.objects.select_related("permission"),
        ),
        "app__scopes",
    )


def serialize_access_grant_rows(
    grants: Sequence[AccessGrant],
    *,
    managed_users_cache: ManagedUsersDirectoryCache | None = None,
) -> list[dict[str, JsonValue]]:
    catalog = expansion_catalog_for_grants(grants)
    cache: ManagedUsersDirectoryCache = {} if managed_users_cache is None else managed_users_cache
    department_labels = department_path_labels(grant.user for grant in grants)
    return [
        serialize_access_grant_row(
            grant,
            managed_users_cache=cache,
            expansion_catalog=catalog,
            department_labels=department_labels,
        )
        for grant in grants
    ]


def serialize_access_grant_row(
    grant: AccessGrant,
    *,
    managed_users_cache: ManagedUsersDirectoryCache | None = None,
    expansion_catalog: GrantExpansionCatalog | None = None,
    department_labels: Mapping[str, str] | None = None,
) -> dict[str, JsonValue]:
    catalog = (
        expansion_catalog
        if expansion_catalog is not None
        else expansion_catalog_for_grants((grant,))
    )
    snapshot = snapshot_for_grant(
        grant,
        managed_users_cache=managed_users_cache,
        expansion_catalog=catalog,
    )
    grant_type, grant_expires_at = grant_lifecycle_summary(snapshot)
    user = grant.user
    labels = department_labels if department_labels is not None else department_path_labels((user,))
    return {
        "id": grant.id,
        "version": grant.version,
        "is_current": grant.is_current,
        "status": grant.status,
        "user_id": user.authentik_user_id,
        "user_name": user.name,
        "user_department": labels.get(user.authentik_user_id, user.department),
        "app_key": grant.app.app_key,
        "app_name": grant.app.name,
        "app_alias": grant.app.alias,
        "grant_type": grant_type,
        "grant_expires_at": datetime_value(grant_expires_at),
        "authorization_groups": _authorization_group_rows(grant),
        "direct_grants": _direct_grant_rows(grant, catalog),
        "groups": json_groups(snapshot.groups),
        "grants": json_expanded_grants(snapshot.grants),
    }


def _authorization_group_rows(grant: AccessGrant) -> list[JsonValue]:
    cache = getattr(grant, "_prefetched_objects_cache", {})
    if "grant_groups" in cache:
        rows = cast(
            "Iterable[AccessGrantGroup]",
            grant.grant_groups.all(),  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        )
    else:
        rows = AccessGrantGroup.objects.select_related("authorization_group").filter(grant=grant)
    items: list[JsonValue] = []
    for link in sorted(rows, key=lambda item: (item.authorization_group.key, item.source)):
        group = link.authorization_group
        items.append(
            {
                "key": group.key,
                "kind": group.kind,
                "name": group.name,
                "expires_at": datetime_value(link.expires_at),
                "source": link.source,
            },
        )
    return items


def _direct_grant_rows(
    grant: AccessGrant,
    catalog: GrantExpansionCatalog,
) -> list[JsonValue]:
    cache = getattr(grant, "_prefetched_objects_cache", {})
    if "grant_permissions" in cache:
        rows = cast(
            "Iterable[AccessGrantPermission]",
            grant.grant_permissions.all(),  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        )
    else:
        rows = AccessGrantPermission.objects.select_related("permission").filter(grant=grant)
    scope_names = {
        scope.key: scope.name for scope in catalog.scopes_by_app_id.get(grant.app_id, ())
    }
    items: list[JsonValue] = []
    for link in sorted(rows, key=lambda item: (item.permission.key, item.scope_key, item.source)):
        permission = link.permission
        items.append(
            {
                "permission": permission.key,
                "permission_name": permission.name,
                "scope": link.scope_key,
                "scope_name": scope_names.get(link.scope_key, link.scope_key),
                "expires_at": datetime_value(link.expires_at),
                "source": link.source,
            },
        )
    return items
