from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue
    from easyauth.grants.query import ExpandedGrant, GroupSnapshot, PermissionSnapshot

__all__: Final = (
    "grant_items",
    "json_expanded_grants",
    "json_groups",
)


def grant_items(snapshot: PermissionSnapshot) -> tuple[dict[str, JsonValue], ...]:
    return tuple(json_expanded_grant(grant) for grant in snapshot.grants)


def json_groups(groups: tuple[GroupSnapshot, ...]) -> list[JsonValue]:
    return [json_group(group) for group in groups]


def json_expanded_grants(grants: tuple[ExpandedGrant, ...]) -> list[JsonValue]:
    return [json_expanded_grant(grant) for grant in grants]


def json_group(group: GroupSnapshot) -> dict[str, JsonValue]:
    return {
        "key": group.key,
        "kind": group.kind,
        "name": group.name,
    }


def json_expanded_grant(grant: ExpandedGrant) -> dict[str, JsonValue]:
    return {
        "permission": grant.permission,
        "scope": grant.scope,
        "source_type": grant.source_type,
        "source_key": grant.source_key,
    }
