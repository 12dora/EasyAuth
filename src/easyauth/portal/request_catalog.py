from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    Permission,
    PermissionGroup,
)

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue


def request_catalog_payload() -> dict[str, JsonValue]:
    authorization_groups = _request_catalog_authorization_groups()
    permissions = _request_catalog_permissions()
    app_ids = {group.app_id for group in authorization_groups} | {
        permission.app_id for permission in permissions
    }
    apps = tuple(App.objects.filter(id__in=app_ids, is_active=True).order_by("app_key"))
    scope_options_by_app_id = _scope_options_by_app_id(tuple(app.id for app in apps))
    return {
        "apps": [_catalog_app_item(app) for app in apps],
        "authorization_groups": [
            _catalog_authorization_group_item(group) for group in authorization_groups
        ],
        "permission_groups": _catalog_permission_groups(permissions, scope_options_by_app_id),
        "ungrouped_permissions": [
            _catalog_permission_item(permission, scope_options_by_app_id)
            for permission in permissions
            if permission.group is None
        ],
    }


def _request_catalog_authorization_groups() -> tuple[AuthorizationGroup, ...]:
    return tuple(
        AuthorizationGroup.objects.select_related("app")
        .filter(
            app__is_active=True,
            is_active=True,
            requestable=True,
        )
        .distinct()
        .order_by("app__app_key", "kind", "key"),
    )


def _request_catalog_permissions() -> tuple[Permission, ...]:
    return tuple(
        Permission.objects.select_related("app", "group")
        .filter(
            app__is_active=True,
            is_active=True,
            deprecated_at__isnull=True,
            approval_rules__is_active=True,
        )
        .distinct()
        .order_by("app__app_key", "group__display_order", "group__key", "key"),
    )


def _catalog_app_item(app: App) -> dict[str, JsonValue]:
    return {
        "id": app.id,
        "app_key": app.app_key,
        "name": app.name,
        "description": app.description,
        "catalog_version": app.catalog_version,
    }


def _catalog_authorization_group_item(group: AuthorizationGroup) -> dict[str, JsonValue]:
    return {
        "id": group.id,
        "app_key": group.app.app_key,
        "key": group.key,
        "kind": group.kind,
        "name": group.name,
        "description": group.description,
        "requestable": group.requestable,
        "requires_approval": True,
    }


def _catalog_permission_groups(
    permissions: tuple[Permission, ...],
    scope_options_by_app_id: dict[int, list[dict[str, JsonValue]]],
) -> list[JsonValue]:
    groups_by_id: dict[int, PermissionGroup] = {}
    permissions_by_group: dict[int, list[Permission]] = {}
    for permission in permissions:
        group = permission.group
        if group is None:
            continue
        permissions_by_group.setdefault(group.id, []).append(permission)
        while group is not None:
            if group.is_active:
                groups_by_id[group.id] = group
            group = group.parent

    children_by_parent: dict[int | None, list[PermissionGroup]] = {}
    for group in sorted(groups_by_id.values(), key=_group_sort_key):
        parent = group.parent
        parent_id = parent.id if parent is not None and parent.id in groups_by_id else None
        children_by_parent.setdefault(parent_id, []).append(group)

    return [
        _catalog_group_item(
            group,
            children_by_parent,
            permissions_by_group,
            scope_options_by_app_id,
        )
        for group in children_by_parent.get(None, [])
    ]


def _catalog_group_item(
    group: PermissionGroup,
    children_by_parent: dict[int | None, list[PermissionGroup]],
    permissions_by_group: dict[int, list[Permission]],
    scope_options_by_app_id: dict[int, list[dict[str, JsonValue]]],
) -> dict[str, JsonValue]:
    permission_items: list[JsonValue] = [
        _catalog_permission_item(permission, scope_options_by_app_id)
        for permission in permissions_by_group.get(group.id, [])
    ]
    children: list[JsonValue] = [
        _catalog_group_item(
            child,
            children_by_parent,
            permissions_by_group,
            scope_options_by_app_id,
        )
        for child in children_by_parent.get(group.id, [])
    ]
    children.extend(permission_items)
    return {
        "id": group.id,
        "app_key": group.app.app_key,
        "type": "group",
        "key": group.key,
        "name": group.name,
        "description": group.description,
        "depth": group.depth,
        "children": children,
        "permissions": permission_items,
    }


def _catalog_permission_item(
    permission: Permission,
    scope_options_by_app_id: dict[int, list[dict[str, JsonValue]]],
) -> dict[str, JsonValue]:
    group = permission.group
    scopes = [
        scope
        for scope in scope_options_by_app_id.get(permission.app_id, [])
        if scope["key"] in permission.supported_scopes
    ]
    return {
        "id": permission.id,
        "app_key": permission.app.app_key,
        "type": "permission",
        "key": permission.key,
        "name": permission.name,
        "description": permission.description,
        "group_key": "" if group is None else group.key,
        "scopes": scopes,
    }


def _group_sort_key(group: PermissionGroup) -> tuple[str, int, int, str]:
    return (group.app.app_key, group.depth, group.display_order, group.key)


def _scope_options_by_app_id(app_ids: tuple[int, ...]) -> dict[int, list[dict[str, JsonValue]]]:
    options_by_app_id: dict[int, list[dict[str, JsonValue]]] = {app_id: [] for app_id in app_ids}
    scopes = AppScope.objects.filter(app_id__in=app_ids, is_active=True).order_by(
        "app_id",
        "display_order",
        "key",
    )
    for scope in scopes:
        options_by_app_id.setdefault(scope.app_id, []).append(
            {"key": scope.key, "name": scope.name, "description": scope.description},
        )
    return options_by_app_id
