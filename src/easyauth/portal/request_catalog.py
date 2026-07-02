from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import (
    App,
    AppMembership,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    Permission,
    PermissionGroup,
)

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue


def request_catalog_payload(user: UserMirror) -> dict[str, JsonValue]:
    apps = tuple(App.objects.filter(is_active=True).order_by("app_key"))
    scope_options_by_app_id = _scope_options_by_app_id(tuple(app.id for app in apps))
    authorization_groups = _request_catalog_authorization_groups()
    permissions = tuple(
        permission
        for permission in _request_catalog_permissions()
        if _permission_scope_options(permission, scope_options_by_app_id)
    )
    approver_users = _active_approver_users()
    resolver = _ApproverResolver(approver_users)
    default_approver_user_ids_by_app_id = _app_default_approver_user_ids_by_app_id(
        apps,
        user,
        resolver,
    )
    default_approver_user_ids_by_group_id = _approval_rule_approvers_by_group_id(
        authorization_groups,
        resolver,
    )
    default_approver_user_ids_by_permission_id = _approval_rule_approvers_by_permission_id(
        permissions,
        resolver,
    )
    return {
        "apps": [
            _catalog_app_item(app, default_approver_user_ids_by_app_id.get(app.id, ()))
            for app in apps
        ],
        "authorization_groups": [
            _catalog_authorization_group_item(
                group,
                default_approver_user_ids_by_group_id.get(group.id)
                or default_approver_user_ids_by_app_id.get(group.app_id, ()),
            )
            for group in authorization_groups
        ],
        "permission_groups": _catalog_permission_groups(
            permissions,
            scope_options_by_app_id,
            default_approver_user_ids_by_app_id,
            default_approver_user_ids_by_permission_id,
        ),
        "ungrouped_permissions": [
            _catalog_permission_item(
                permission,
                scope_options_by_app_id,
                default_approver_user_ids_by_permission_id.get(permission.id)
                or default_approver_user_ids_by_app_id.get(permission.app_id, ()),
            )
            for permission in permissions
            if permission.group is None
        ],
        "approver_options": [_approver_option(user) for user in approver_users],
    }


def _request_catalog_authorization_groups() -> tuple[AuthorizationGroup, ...]:
    return tuple(
        AuthorizationGroup.objects.select_related("app")
        .filter(
            app__is_active=True,
            is_active=True,
            requestable=True,
            approval_rules__is_active=True,
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
        )
        .distinct()
        .order_by("app__app_key", "group__display_order", "group__key", "key"),
    )


def _catalog_app_item(
    app: App,
    default_approver_user_ids: tuple[str, ...],
) -> dict[str, JsonValue]:
    return {
        "id": app.id,
        "app_key": app.app_key,
        "name": app.name,
        "description": app.description,
        "catalog_version": app.catalog_version,
        "default_approver_user_ids": _json_strings(default_approver_user_ids),
    }


def _catalog_authorization_group_item(
    group: AuthorizationGroup,
    default_approver_user_ids: tuple[str, ...],
) -> dict[str, JsonValue]:
    return {
        "id": group.id,
        "app_key": group.app.app_key,
        "key": group.key,
        "kind": group.kind,
        "name": group.name,
        "description": group.description,
        "requestable": group.requestable,
        "requires_approval": True,
        "default_approver_user_ids": _json_strings(default_approver_user_ids),
    }


def _catalog_permission_groups(
    permissions: tuple[Permission, ...],
    scope_options_by_app_id: dict[int, list[dict[str, JsonValue]]],
    default_approver_user_ids_by_app_id: dict[int, tuple[str, ...]],
    default_approver_user_ids_by_permission_id: dict[int, tuple[str, ...]],
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
            default_approver_user_ids_by_app_id,
            default_approver_user_ids_by_permission_id,
        )
        for group in children_by_parent.get(None, [])
    ]


def _catalog_group_item(
    group: PermissionGroup,
    children_by_parent: dict[int | None, list[PermissionGroup]],
    permissions_by_group: dict[int, list[Permission]],
    scope_options_by_app_id: dict[int, list[dict[str, JsonValue]]],
    default_approver_user_ids_by_app_id: dict[int, tuple[str, ...]],
    default_approver_user_ids_by_permission_id: dict[int, tuple[str, ...]],
) -> dict[str, JsonValue]:
    permission_items: list[JsonValue] = [
        _catalog_permission_item(
            permission,
            scope_options_by_app_id,
            default_approver_user_ids_by_permission_id.get(permission.id)
            or default_approver_user_ids_by_app_id.get(permission.app_id, ()),
        )
        for permission in permissions_by_group.get(group.id, [])
    ]
    children: list[JsonValue] = [
        _catalog_group_item(
            child,
            children_by_parent,
            permissions_by_group,
            scope_options_by_app_id,
            default_approver_user_ids_by_app_id,
            default_approver_user_ids_by_permission_id,
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
    default_approver_user_ids: tuple[str, ...],
) -> dict[str, JsonValue]:
    group = permission.group
    scopes = _permission_scope_options(permission, scope_options_by_app_id)
    return {
        "id": permission.id,
        "app_key": permission.app.app_key,
        "type": "permission",
        "key": permission.key,
        "name": permission.name,
        "description": permission.description,
        "group_key": "" if group is None else group.key,
        "scopes": scopes,
        "default_approver_user_ids": _json_strings(default_approver_user_ids),
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


def _permission_scope_options(
    permission: Permission,
    scope_options_by_app_id: dict[int, list[dict[str, JsonValue]]],
) -> list[dict[str, JsonValue]]:
    return [
        scope
        for scope in scope_options_by_app_id.get(permission.app_id, [])
        if scope["key"] in permission.supported_scopes
    ]


def _active_approver_users() -> tuple[UserMirror, ...]:
    return tuple(
        UserMirror.objects.filter(status=USER_STATUS_ACTIVE).order_by("authentik_user_id"),
    )


def _approver_option(user: UserMirror) -> dict[str, JsonValue]:
    return {
        "user_id": user.authentik_user_id,
        "name": user.name,
        "email": user.email,
        "department": user.department,
    }


def _app_default_approver_user_ids_by_app_id(
    apps: tuple[App, ...],
    user: UserMirror,
    resolver: _ApproverResolver,
) -> dict[int, tuple[str, ...]]:
    app_ids = tuple(app.id for app in apps)
    owner_user_ids_by_app_id = _owner_user_ids_by_app_id(app_ids)
    manager_user_ids = resolver.resolve((user.manager_userid,))
    return {
        app.id: manager_user_ids or resolver.resolve(owner_user_ids_by_app_id.get(app.id, ()))
        for app in apps
    }


def _owner_user_ids_by_app_id(app_ids: tuple[int, ...]) -> dict[int, tuple[str, ...]]:
    owner_user_ids_by_app_id: dict[int, list[str]] = {app_id: [] for app_id in app_ids}
    memberships = AppMembership.objects.filter(
        app_id__in=app_ids,
        role="owner",
        is_active=True,
    ).order_by("app_id", "user_id")
    for membership in memberships:
        owner_user_ids_by_app_id.setdefault(membership.app_id, []).append(membership.user_id)
    return {
        app_id: tuple(owner_user_ids)
        for app_id, owner_user_ids in owner_user_ids_by_app_id.items()
    }


def _approval_rule_approvers_by_group_id(
    groups: tuple[AuthorizationGroup, ...],
    resolver: _ApproverResolver,
) -> dict[int, tuple[str, ...]]:
    group_ids = tuple(group.id for group in groups)
    if not group_ids:
        return {}
    defaults: dict[int, tuple[str, ...]] = {}
    rules = ApprovalRule.objects.filter(
        authorization_group_id__in=group_ids,
        is_active=True,
    ).order_by("authorization_group_id", "id")
    for rule in rules:
        if rule.authorization_group_id in defaults:
            continue
        approver_user_ids = resolver.resolve(rule.approver_userids)
        if approver_user_ids:
            defaults[rule.authorization_group_id] = approver_user_ids
    return defaults


def _approval_rule_approvers_by_permission_id(
    permissions: tuple[Permission, ...],
    resolver: _ApproverResolver,
) -> dict[int, tuple[str, ...]]:
    permission_ids = tuple(permission.id for permission in permissions)
    if not permission_ids:
        return {}
    defaults: dict[int, tuple[str, ...]] = {}
    rules = ApprovalRule.objects.filter(
        permission_id__in=permission_ids,
        is_active=True,
    ).order_by("permission_id", "id")
    for rule in rules:
        if rule.permission_id in defaults:
            continue
        approver_user_ids = resolver.resolve(rule.approver_userids)
        if approver_user_ids:
            defaults[rule.permission_id] = approver_user_ids
    return defaults


class _ApproverResolver:
    def __init__(self, users: tuple[UserMirror, ...]) -> None:
        self._user_id_by_authentik_user_id = {
            user.authentik_user_id: user.authentik_user_id for user in users
        }
        self._user_id_by_dingtalk_userid = {
            user.dingtalk_userid: user.authentik_user_id
            for user in users
            if user.dingtalk_userid
        }

    def resolve(self, raw_user_ids: object) -> tuple[str, ...]:
        if not isinstance(raw_user_ids, (list, tuple)):
            return ()
        resolved_user_ids: list[str] = []
        seen: set[str] = set()
        for raw_user_id in raw_user_ids:
            if not isinstance(raw_user_id, str):
                continue
            user_id = self._user_id_by_authentik_user_id.get(
                raw_user_id,
            ) or self._user_id_by_dingtalk_userid.get(raw_user_id)
            if user_id is None or user_id in seen:
                continue
            seen.add(user_id)
            resolved_user_ids.append(user_id)
        return tuple(resolved_user_ids)


def _json_strings(values: tuple[str, ...]) -> list[JsonValue]:
    result: list[JsonValue] = []
    result.extend(values)
    return result
