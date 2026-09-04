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
    # 中文展示名由 grants.query._with_catalog_names 统一挂上(目录行缺失时已回退为 key);
    # 到这里仍为空说明快照没走过目录解析, 是编程错误, 不能再用 key 糊过去。
    if not grant.permission_name or not grant.scope_name:
        message = f"授权项 {grant.permission}:{grant.scope} 缺少目录展示名, 快照未经过目录解析"
        raise ValueError(message)
    return {
        "permission": grant.permission,
        "scope": grant.scope,
        "source_type": grant.source_type,
        "source_key": grant.source_key,
        "permission_name": grant.permission_name,
        "permission_name_en": grant.permission_name_en,
        "scope_name": grant.scope_name,
        "scope_name_en": grant.scope_name_en,
    }
