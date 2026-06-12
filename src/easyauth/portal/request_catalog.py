from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.applications.models import App, Permission, PermissionGroup, Role

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue


def request_catalog_payload() -> dict[str, JsonValue]:
    roles = _request_catalog_roles()
    permissions = _request_catalog_permissions()
    app_ids = {role.app_id for role in roles} | {permission.app_id for permission in permissions}
    apps = tuple(App.objects.filter(id__in=app_ids, is_active=True).order_by("app_key"))
    return {
        "apps": [_catalog_app_item(app) for app in apps],
        "roles": [_catalog_role_item(role) for role in roles],
        "permission_groups": _catalog_permission_groups(permissions),
        "ungrouped_permissions": [
            _catalog_permission_item(permission)
            for permission in permissions
            if permission.group is None
        ],
    }


def _request_catalog_roles() -> tuple[Role, ...]:
    return tuple(
        Role.objects.select_related("app")
        .filter(
            app__is_active=True,
            is_active=True,
            requestable=True,
            approval_rules__is_active=True,
        )
        .distinct()
        .order_by("app__app_key", "key"),
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
    }


def _catalog_role_item(role: Role) -> dict[str, JsonValue]:
    return {
        "id": role.id,
        "app_key": role.app.app_key,
        "key": role.key,
        "name": role.name,
        "description": role.description,
        "requestable": role.requestable,
        "requires_approval": True,
    }


def _catalog_permission_groups(permissions: tuple[Permission, ...]) -> list[JsonValue]:
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
        _catalog_group_item(group, children_by_parent, permissions_by_group)
        for group in children_by_parent.get(None, [])
    ]


def _catalog_group_item(
    group: PermissionGroup,
    children_by_parent: dict[int | None, list[PermissionGroup]],
    permissions_by_group: dict[int, list[Permission]],
) -> dict[str, JsonValue]:
    permission_items: list[JsonValue] = [
        _catalog_permission_item(permission)
        for permission in permissions_by_group.get(group.id, [])
    ]
    children: list[JsonValue] = [
        _catalog_group_item(child, children_by_parent, permissions_by_group)
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


def _catalog_permission_item(permission: Permission) -> dict[str, JsonValue]:
    group = permission.group
    return {
        "id": permission.id,
        "app_key": permission.app.app_key,
        "type": "permission",
        "key": permission.key,
        "name": permission.name,
        "description": permission.description,
        "group_key": "" if group is None else group.key,
    }


def _group_sort_key(group: PermissionGroup) -> tuple[str, int, int, str]:
    return (group.app.app_key, group.depth, group.display_order, group.key)
