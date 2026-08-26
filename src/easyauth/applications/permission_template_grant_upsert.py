"""写入授权组 grant, 并提供 preview 用的 grant 集合投影。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.applications.models import AuthorizationGroupGrant

if TYPE_CHECKING:
    from collections.abc import Iterable

    from easyauth.applications.models import App, AuthorizationGroup, Permission
    from easyauth.applications.permission_template_types import (
        AppManifestAuthorizationGroupInput,
        AppManifestInput,
    )

type _GrantFingerprint = tuple[str, str, bool]

__all__ = [
    "_grant_sets_by_group_id",
    "_incoming_grant_set",
    "_upsert_authorization_group_grants",
]


def _upsert_authorization_group_grants(
    *,
    manifest: AppManifestInput,
    authorization_group_by_key: dict[str, AuthorizationGroup],
    permission_by_key: dict[str, Permission],
) -> None:
    incoming_grants = {
        (group.key, grant.permission, grant.scope): grant
        for group in manifest.authorization_groups
        for grant in group.grants
    }
    existing_grants = {
        (grant.authorization_group.key, grant.permission.key, grant.scope_key): grant
        for grant in AuthorizationGroupGrant.objects.filter(
            authorization_group__in=authorization_group_by_key.values(),
        ).select_related("authorization_group", "permission")
    }
    for (group_key, permission_key, scope_key), spec in incoming_grants.items():
        grant = existing_grants.get(
            (group_key, permission_key, scope_key),
        ) or AuthorizationGroupGrant(
            authorization_group=authorization_group_by_key[group_key],
            permission=permission_by_key[permission_key],
            scope_key=scope_key,
        )
        grant.is_active = spec.is_active
        grant.full_clean()
        grant.save()
    for key, grant in existing_grants.items():
        if key not in incoming_grants and grant.is_active:
            grant.is_active = False
            grant.full_clean()
            grant.save(update_fields=["is_active", "updated_at"])


def _grant_sets_by_group_id(app: App) -> dict[int, set[_GrantFingerprint]]:
    """一次性预加载该 App 下全部授权组 grant, 按 group id 建索引, 避免 preview N+1。"""
    grouped: dict[int, list[AuthorizationGroupGrant]] = {}
    for grant in AuthorizationGroupGrant.objects.filter(
        authorization_group__app=app,
    ).select_related("permission"):
        grouped.setdefault(grant.authorization_group_id, []).append(grant)
    return {group_id: _grant_set(grants) for group_id, grants in grouped.items()}


def _grant_set(grants: Iterable[AuthorizationGroupGrant]) -> set[_GrantFingerprint]:
    return {(grant.permission.key, grant.scope_key, grant.is_active) for grant in grants}


def _incoming_grant_set(group: AppManifestAuthorizationGroupInput) -> set[_GrantFingerprint]:
    return {(grant.permission, grant.scope, grant.is_active) for grant in group.grants}
