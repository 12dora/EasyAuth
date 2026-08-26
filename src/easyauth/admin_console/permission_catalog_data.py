from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Prefetch, QuerySet

from easyauth.admin_console.api_payloads import list_payload
from easyauth.admin_console.permission_catalog_policy_data import (
    ManagedScopePolicyContext,
    effective_managed_scope_policy_item,
    grant_managed_scope_policy_item,
    managed_scope_policy_context,
)
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
    PermissionGroup,
)

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue


def permission_tree_payload(app: App) -> dict[str, JsonValue]:
    groups = active_groups(app)
    children_by_parent: dict[int | None, list[PermissionGroup]] = {}
    for group in groups:
        parent = group.parent
        parent_id = None if parent is None else parent.id
        children_by_parent.setdefault(parent_id, []).append(group)
    permissions_by_group = _permissions_by_group(app)
    return {
        "app_key": app.app_key,
        "groups": [
            _group_tree_item(group, children_by_parent, permissions_by_group)
            for group in children_by_parent.get(None, [])
        ],
        "ungrouped_permissions": [
            permission_item(permission) for permission in permissions_by_group.get(None, [])
        ],
        "catalog_version": app.catalog_version,
        "version": catalog_version(app),
    }


def permission_groups_payload(app: App) -> dict[str, JsonValue]:
    return {
        "app_key": app.app_key,
        **list_payload([group_item(group) for group in active_groups(app)]),
        "catalog_version": app.catalog_version,
        "version": catalog_version(app),
    }


def scopes_payload(app: App) -> dict[str, JsonValue]:
    return {
        "app_key": app.app_key,
        **list_payload([scope_item(scope) for scope in active_scopes(app)]),
        "catalog_version": app.catalog_version,
        "version": catalog_version(app),
    }


def authorization_groups_payload(
    app: App,
    *,
    include_inactive: bool = False,
    status: str = "",
) -> dict[str, JsonValue]:
    groups = active_authorization_groups(app, include_inactive=include_inactive, status=status)
    return authorization_groups_page_payload(app, groups=groups)


def authorization_groups_page_payload(
    app: App,
    *,
    groups: tuple[AuthorizationGroup, ...],
    pagination: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    policy_context = managed_scope_policy_context(app, groups)
    payload: dict[str, JsonValue] = {
        "app_key": app.app_key,
        **list_payload(
            [authorization_group_item(group, policy_context=policy_context) for group in groups],
        ),
        "catalog_version": app.catalog_version,
        "version": catalog_version(app),
    }
    if pagination is not None:
        payload["pagination"] = pagination
    return payload


def permissions_payload(app: App) -> dict[str, JsonValue]:
    return {
        "app_key": app.app_key,
        **list_payload([permission_item(permission) for permission in active_permissions(app)]),
        "catalog_version": app.catalog_version,
        "version": catalog_version(app),
    }


def active_groups(app: App) -> tuple[PermissionGroup, ...]:
    return tuple(
        PermissionGroup.objects.filter(app=app, is_active=True)
        .select_related("parent")
        .order_by("depth", "display_order", "key"),
    )


def active_scopes(app: App) -> tuple[AppScope, ...]:
    return tuple(AppScope.objects.filter(app=app).order_by("display_order", "key"))


def active_authorization_groups(
    app: App,
    *,
    include_inactive: bool = False,
    status: str = "",
) -> tuple[AuthorizationGroup, ...]:
    return tuple(
        active_authorization_groups_queryset(
            app,
            include_inactive=include_inactive,
            status=status,
        )
    )


def active_authorization_groups_queryset(
    app: App,
    *,
    include_inactive: bool = False,
    status: str = "",
) -> QuerySet[AuthorizationGroup]:
    grants = AuthorizationGroupGrant.objects.select_related("permission").order_by(
        "permission__key",
        "scope_key",
    )
    queryset = AuthorizationGroup.objects.filter(app=app)
    match status:
        case "active":
            queryset = queryset.filter(is_active=True)
        case "inactive":
            queryset = queryset.filter(is_active=False)
        case "":
            if not include_inactive:
                queryset = queryset.filter(is_active=True)
        case _:
            queryset = queryset.none()
    return (
        queryset.select_related("app")
        .prefetch_related(Prefetch("grants", queryset=grants, to_attr="_prefetched_grants"))
        .order_by("kind", "key")
    )


def active_permissions(app: App) -> tuple[Permission, ...]:
    return tuple(
        Permission.objects.filter(app=app, is_active=True, deprecated_at__isnull=True)
        .select_related("group")
        .order_by("group__display_order", "group__key", "key"),
    )


def catalog_version(app: App) -> str:
    return str(app.catalog_version)


def group_item(group: PermissionGroup) -> dict[str, JsonValue]:
    parent_key = ""
    if group.parent is not None:
        parent_key = group.parent.key
    return {
        "id": group.id,
        "type": "group",
        "key": group.key,
        "name": group.name,
        "name_en": group.name_en,
        "description": group.description,
        "description_en": group.description_en,
        "parent_key": parent_key,
        "depth": group.depth,
        "display_order": group.display_order,
        "is_active": group.is_active,
    }


def scope_item(scope: AppScope) -> dict[str, JsonValue]:
    return {
        "id": scope.id,
        "key": scope.key,
        "name": scope.name,
        "name_en": scope.name_en,
        "description": scope.description,
        "description_en": scope.description_en,
        "is_active": scope.is_active,
        "display_order": scope.display_order,
    }


def authorization_group_item(
    group: AuthorizationGroup,
    *,
    policy_context: ManagedScopePolicyContext | None = None,
) -> dict[str, JsonValue]:
    grants = tuple(
        getattr(
            group,
            "_prefetched_grants",
            AuthorizationGroupGrant.objects.filter(authorization_group=group)
            .select_related("permission")
            .order_by("permission__key", "scope_key"),
        ),
    )
    return {
        "id": group.id,
        "app_key": group.app.app_key,
        "key": group.key,
        "kind": group.kind,
        "name": group.name,
        "name_en": group.name_en,
        "description": group.description,
        "description_en": group.description_en,
        "requestable": group.requestable,
        "is_active": group.is_active,
        "grants": [
            authorization_group_grant_item(grant, policy_context=policy_context) for grant in grants
        ],
    }


def authorization_group_grant_item(
    grant: AuthorizationGroupGrant,
    *,
    policy_context: ManagedScopePolicyContext | None = None,
) -> dict[str, JsonValue]:
    return {
        "permission": grant.permission.key,
        "scope": grant.scope_key,
        "is_active": grant.is_active,
        "managed_scope_policy": grant_managed_scope_policy_item(
            grant,
            policy_context=policy_context,
        ),
        "effective_managed_scope_policy": effective_managed_scope_policy_item(
            grant,
            policy_context=policy_context,
        ),
    }


def permission_item(permission: Permission) -> dict[str, JsonValue]:
    group_key = ""
    if permission.group is not None:
        group_key = permission.group.key
    deprecated_at = permission.deprecated_at
    return {
        "id": permission.id,
        "type": "permission",
        "key": permission.key,
        "name": permission.name,
        "name_en": permission.name_en,
        "description": permission.description,
        "description_en": permission.description_en,
        "group_key": group_key,
        "is_active": permission.is_active,
        "is_deprecated": permission.deprecated_at is not None,
        "deprecated_at": None if deprecated_at is None else deprecated_at.isoformat(),
        "deprecated_reason": permission.deprecated_reason,
        "supported_scopes": permission.supported_scopes,
        "risk_level": permission.risk_level,
    }


def _group_tree_item(
    group: PermissionGroup,
    children_by_parent: dict[int | None, list[PermissionGroup]],
    permissions_by_group: dict[int | None, list[Permission]],
) -> dict[str, JsonValue]:
    permission_items: list[JsonValue] = []
    permission_items.extend(
        permission_item(permission) for permission in permissions_by_group.get(group.id, [])
    )
    children: list[JsonValue] = []
    children.extend(
        _group_tree_item(child, children_by_parent, permissions_by_group)
        for child in children_by_parent.get(group.id, [])
    )
    children.extend(permission_items)
    return {
        **group_item(group),
        "children": children,
        "permissions": permission_items,
    }


def _permissions_by_group(app: App) -> dict[int | None, list[Permission]]:
    permissions_by_group: dict[int | None, list[Permission]] = {}
    for permission in active_permissions(app):
        group = permission.group
        group_id = None if group is None else group.id
        permissions_by_group.setdefault(group_id, []).append(permission)
    return permissions_by_group
