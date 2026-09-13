"""授权组成员与直接授权行的共享形状。控制台授权行与门户当前授权共用。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from easyauth.api.datetime_json import datetime_value
from easyauth.grants.models import AccessGrantGroup, AccessGrantPermission

if TYPE_CHECKING:
    from collections.abc import Iterable

    from easyauth.api.errors import JsonValue
    from easyauth.grants.models import AccessGrant
    from easyauth.grants.query import GrantExpansionCatalog

__all__: Final = (
    "authorization_group_items",
    "direct_grant_items",
)


def authorization_group_items(grant: AccessGrant) -> list[JsonValue]:
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


def direct_grant_items(
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
