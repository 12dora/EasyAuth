from __future__ import annotations

from typing import TYPE_CHECKING, Final

from django.db.models import Prefetch, QuerySet

from easyauth.accounts.department_paths import department_path_labels
from easyauth.accounts.person_payload import person_row_fields
from easyauth.api.datetime_json import datetime_value
from easyauth.applications.models import AuthorizationGroupGrant
from easyauth.grants.grant_row_items import authorization_group_items, direct_grant_items
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission
from easyauth.grants.permission_aggregation import grant_lifecycle_summary
from easyauth.grants.query import (
    GrantExpansionCatalog,
    expansion_catalog_for_grants,
    snapshot_for_grant,
)
from easyauth.portal.permission_aggregation import json_expanded_grants, json_groups

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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
        **person_row_fields(user, labels),
        "app_key": grant.app.app_key,
        "app_name": grant.app.name,
        "app_alias": grant.app.alias,
        "grant_type": grant_type,
        "grant_expires_at": datetime_value(grant_expires_at),
        "authorization_groups": authorization_group_items(grant),
        "direct_grants": direct_grant_items(grant, catalog),
        "groups": json_groups(snapshot.groups),
        "grants": json_expanded_grants(snapshot.grants),
    }
