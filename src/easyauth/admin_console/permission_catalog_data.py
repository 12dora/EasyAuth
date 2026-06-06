from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

from easyauth.admin_console.api_payloads import list_payload
from easyauth.applications.models import App, Permission, PermissionGroup, Role, RolePermission

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
        "version": catalog_version(app),
    }


def permission_groups_payload(app: App) -> dict[str, JsonValue]:
    return {
        "app_key": app.app_key,
        **list_payload([group_item(group) for group in active_groups(app)]),
        "version": catalog_version(app),
    }


def roles_payload(app: App) -> dict[str, JsonValue]:
    return {
        "app_key": app.app_key,
        **list_payload([role_item(role) for role in active_roles(app)]),
        "version": catalog_version(app),
    }


def permissions_payload(app: App) -> dict[str, JsonValue]:
    return {
        "app_key": app.app_key,
        **list_payload([permission_item(permission) for permission in active_permissions(app)]),
        "version": catalog_version(app),
    }


def matrix_payload(app: App) -> dict[str, JsonValue]:
    roles = active_roles(app)
    permissions = active_permissions(app)
    enabled_pairs = _enabled_pairs(roles, permissions)
    return {
        "app_key": app.app_key,
        "roles": [role_item(role) for role in roles],
        "permissions": [permission_item(permission) for permission in permissions],
        "permission_tree": permission_tree_payload(app)["groups"],
        "assignments": [
            {
                "role_key": role.key,
                "permission_key": permission.key,
            }
            for role in roles
            for permission in permissions
            if (role.id, permission.id) in enabled_pairs
        ],
        "cells": [
            {
                "role_id": role.id,
                "permission_id": permission.id,
                "enabled": (role.id, permission.id) in enabled_pairs,
            }
            for permission in permissions
            for role in roles
        ],
        "version": catalog_version(app),
    }


def matrix_objects(
    app: App,
    *,
    role_id: int,
    permission_id: int,
) -> tuple[Role, Permission] | None:
    role = Role.objects.filter(app=app, id=role_id, is_active=True).first()
    permission = Permission.objects.filter(
        app=app,
        id=permission_id,
        is_active=True,
        deprecated_at__isnull=True,
    ).first()
    if role is None or permission is None:
        return None
    return role, permission


def matrix_objects_by_key(
    app: App,
    *,
    role_key: str,
    permission_key: str,
) -> tuple[Role, Permission] | None:
    role = Role.objects.filter(app=app, key=role_key, is_active=True).first()
    permission = Permission.objects.filter(
        app=app,
        key=permission_key,
        is_active=True,
        deprecated_at__isnull=True,
    ).first()
    if role is None or permission is None:
        return None
    return role, permission


def active_groups(app: App) -> tuple[PermissionGroup, ...]:
    return tuple(
        PermissionGroup.objects.filter(app=app, is_active=True)
        .select_related("parent")
        .order_by("depth", "display_order", "key"),
    )


def active_roles(app: App) -> tuple[Role, ...]:
    return tuple(Role.objects.filter(app=app, is_active=True).order_by("key"))


def active_permissions(app: App) -> tuple[Permission, ...]:
    return tuple(
        Permission.objects.filter(app=app, is_active=True, deprecated_at__isnull=True)
        .select_related("group")
        .order_by("group__display_order", "group__key", "key"),
    )


def catalog_version(app: App) -> str:
    hasher = sha256()
    for group in active_groups(app):
        hasher.update(f"group:{group.id}:{group.key}:{group.updated_at.isoformat()}|".encode())
    for role in active_roles(app):
        hasher.update(f"role:{role.id}:{role.key}:{role.updated_at.isoformat()}|".encode())
    for permission in active_permissions(app):
        hasher.update(
            f"permission:{permission.id}:{permission.key}:{permission.updated_at.isoformat()}|".encode(),
        )
    links = RolePermission.objects.filter(role__app=app).order_by("role_id", "permission_id")
    for link in links:
        hasher.update(
            f"link:{link.role_id}:{link.permission_id}:{link.created_at.isoformat()}|".encode(),
        )
    return hasher.hexdigest()


def group_item(group: PermissionGroup) -> dict[str, JsonValue]:
    parent_key = ""
    if group.parent is not None:
        parent_key = group.parent.key
    return {
        "id": group.id,
        "type": "group",
        "key": group.key,
        "name": group.name,
        "description": group.description,
        "parent_id": None if group.parent is None else group.parent.id,
        "parent_key": parent_key,
        "depth": group.depth,
        "display_order": group.display_order,
        "is_active": group.is_active,
    }


def role_item(role: Role) -> dict[str, JsonValue]:
    return {
        "id": role.id,
        "key": role.key,
        "name": role.name,
        "description": role.description,
        "requestable": role.requestable,
        "is_active": role.is_active,
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
        "description": permission.description,
        "group_id": None if permission.group is None else permission.group.id,
        "group_key": group_key,
        "is_active": permission.is_active,
        "is_deprecated": permission.deprecated_at is not None,
        "deprecated_at": None if deprecated_at is None else deprecated_at.isoformat(),
        "deprecated_reason": permission.deprecated_reason,
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


def _enabled_pairs(
    roles: tuple[Role, ...],
    permissions: tuple[Permission, ...],
) -> set[tuple[int, int]]:
    return {
        (link.role_id, link.permission_id)
        for link in RolePermission.objects.filter(
            role_id__in=[role.id for role in roles],
            permission_id__in=[permission.id for permission in permissions],
        )
    }
