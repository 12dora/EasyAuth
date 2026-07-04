from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.admin_console.api_payloads import list_payload
from easyauth.applications.managed_scope_policy import ManagedScopePolicyService
from easyauth.applications.models import (
    MANAGED_SCOPE_POLICY_RESOLVER_DINGTALK_MANAGER_CHAIN,
    MANAGED_SCOPE_POLICY_RESOLVER_DISABLED,
    MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
    MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
    MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    ManagedScopePolicy,
    Permission,
    PermissionGroup,
    Role,
    RolePermission,
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


def roles_payload(app: App) -> dict[str, JsonValue]:
    return {
        "app_key": app.app_key,
        **list_payload([role_item(role) for role in active_roles(app)]),
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


def authorization_groups_payload(app: App) -> dict[str, JsonValue]:
    groups = [authorization_group_item(group) for group in active_authorization_groups(app)]
    return {
        "app_key": app.app_key,
        **list_payload(groups),
        "catalog_version": app.catalog_version,
        "version": catalog_version(app),
    }


def permissions_payload(app: App) -> dict[str, JsonValue]:
    return {
        "app_key": app.app_key,
        **list_payload([permission_item(permission) for permission in active_permissions(app)]),
        "catalog_version": app.catalog_version,
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
        "catalog_version": app.catalog_version,
        "version": catalog_version(app),
    }


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


def active_scopes(app: App) -> tuple[AppScope, ...]:
    return tuple(AppScope.objects.filter(app=app).order_by("display_order", "key"))


def active_authorization_groups(app: App) -> tuple[AuthorizationGroup, ...]:
    return tuple(
        AuthorizationGroup.objects.filter(app=app, is_active=True)
        .prefetch_related("grants__permission")
        .order_by("kind", "key"),
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


def role_item(role: Role) -> dict[str, JsonValue]:
    return {
        "id": role.id,
        "key": role.key,
        "name": role.name,
        "description": role.description,
        "requestable": role.requestable,
        "is_active": role.is_active,
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


def authorization_group_item(group: AuthorizationGroup) -> dict[str, JsonValue]:
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
            authorization_group_grant_item(grant)
            for grant in AuthorizationGroupGrant.objects.filter(authorization_group=group)
            .select_related("permission")
            .order_by("permission__key", "scope_key")
        ],
    }


def authorization_group_grant_item(grant: AuthorizationGroupGrant) -> dict[str, JsonValue]:
    return {
        "permission": grant.permission.key,
        "scope": grant.scope_key,
        "is_active": grant.is_active,
        "managed_scope_policy": _grant_managed_scope_policy_item(grant),
        "effective_managed_scope_policy": _effective_managed_scope_policy_item(grant),
    }


def _grant_managed_scope_policy_item(grant: AuthorizationGroupGrant) -> dict[str, JsonValue]:
    override = ManagedScopePolicyService.get_grant_override_policy(
        app=grant.authorization_group.app,
        grant=grant,
    )
    if override is not None:
        return {
            "mode": _managed_scope_policy_mode(override),
            "resolver": override.resolver,
            "enabled": override.enabled,
            "source": MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
            "health_status": _managed_scope_policy_health(override),
            "health_message": _managed_scope_policy_health_message(override),
        }
    app_default = ManagedScopePolicyService.get_app_default_policy(
        app=grant.authorization_group.app,
    )
    if app_default is not None:
        return {
            "mode": "inherit",
            "resolver": "",
            "enabled": False,
            "source": MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
            "health_status": "healthy",
            "health_message": "继承应用默认管理范围策略。",
        }
    return {
        "mode": "inherit",
        "resolver": "",
        "enabled": False,
        "source": "",
        "health_status": "blocked",
        "health_message": "必须配置管理范围计算方式后才能生效。",
    }


def _effective_managed_scope_policy_item(
    grant: AuthorizationGroupGrant,
) -> dict[str, JsonValue] | None:
    effective = ManagedScopePolicyService.get_effective_policy(
        app=grant.authorization_group.app,
        grant=grant,
    )
    if effective is None:
        return None
    return {
        "resolver": effective.resolver,
        "enabled": effective.policy.enabled,
        "source": effective.source,
        "inherited_from": effective.inherited_from,
        "health_status": "healthy",
        "health_message": "管理范围策略已配置。",
    }


def _managed_scope_policy_mode(policy: ManagedScopePolicy) -> str:
    if policy.resolver == MANAGED_SCOPE_POLICY_RESOLVER_DISABLED:
        return MANAGED_SCOPE_POLICY_RESOLVER_DISABLED
    if policy.resolver == MANAGED_SCOPE_POLICY_RESOLVER_DINGTALK_MANAGER_CHAIN:
        return "override"
    return policy.resolver


def _managed_scope_policy_health(policy: ManagedScopePolicy) -> str:
    if not policy.enabled or policy.resolver == MANAGED_SCOPE_POLICY_RESOLVER_DISABLED:
        return "disabled"
    if policy.scope != MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS:
        return "invalid"
    return "healthy"


def _managed_scope_policy_health_message(policy: ManagedScopePolicy) -> str:
    if not policy.enabled or policy.resolver == MANAGED_SCOPE_POLICY_RESOLVER_DISABLED:
        return "当前 grant 不启用管理范围授权。"
    if policy.scope != MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS:
        return "管理范围策略 scope 无效。"
    return "管理范围策略已配置。"


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
