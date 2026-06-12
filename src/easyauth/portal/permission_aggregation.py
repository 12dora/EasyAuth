from __future__ import annotations

from typing import Final

from easyauth.applications.models import RolePermission
from easyauth.grants.models import AccessGrantPermission

__all__: Final = (
    "direct_permission_keys_by_grant_id",
    "permission_keys",
    "role_permission_keys_by_role_id",
)


def direct_permission_keys_by_grant_id(
    grant_ids: tuple[int, ...],
    *,
    active_only: bool = True,
) -> dict[int, set[str]]:
    permission_keys_by_grant_id: dict[int, set[str]] = {grant_id: set() for grant_id in grant_ids}
    links = AccessGrantPermission.objects.select_related("permission").filter(
        grant_id__in=grant_ids,
    )
    if active_only:
        links = links.filter(
            permission__is_active=True,
            permission__deprecated_at__isnull=True,
        )
    for link in links.order_by("grant_id", "permission__key"):
        permission_keys_by_grant_id.setdefault(link.grant_id, set()).add(link.permission.key)
    return permission_keys_by_grant_id


def role_permission_keys_by_role_id(
    role_ids: tuple[int, ...],
    *,
    active_only: bool = True,
) -> dict[int, set[str]]:
    permission_keys_by_role_id: dict[int, set[str]] = {role_id: set() for role_id in role_ids}
    links = RolePermission.objects.select_related("permission").filter(role_id__in=role_ids)
    if active_only:
        links = links.filter(
            role__is_active=True,
            permission__is_active=True,
            permission__deprecated_at__isnull=True,
        )
    for link in links.order_by("role_id", "permission__key"):
        permission_keys_by_role_id.setdefault(link.role_id, set()).add(link.permission.key)
    return permission_keys_by_role_id


def permission_keys(
    *,
    direct_permission_keys: set[str],
    role_ids: tuple[int, ...],
    role_permission_keys_by_role_id: dict[int, set[str]],
) -> tuple[str, ...]:
    aggregated_permission_keys = set(direct_permission_keys)
    for role_id in role_ids:
        aggregated_permission_keys.update(role_permission_keys_by_role_id.get(role_id, set()))
    return tuple(sorted(aggregated_permission_keys))
