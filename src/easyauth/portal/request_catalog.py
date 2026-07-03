from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import (
    App,
    AppMembership,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
    PermissionGroup,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from easyauth.api.errors import JsonValue

MANAGED_USERS_SCOPE = "MANAGED_USERS"
APPROVER_RESOLUTION_DEFAULT_POLICY = "default_policy"
APPROVER_RESOLUTION_DIRECT_MANAGER_MISSING = "direct_manager_missing"
APPROVER_RESOLUTION_RESOLVED_BY_DIRECT_MANAGER = "resolved_by_direct_manager"


@dataclass(frozen=True, slots=True)
class _ApproverResolution:
    user_ids: tuple[str, ...]
    status: str


@dataclass(frozen=True, slots=True)
class _PermissionCatalogContext:
    scope_options_by_app_id: dict[int, list[dict[str, JsonValue]]]
    default_approver_by_app_id: dict[int, _ApproverResolution]
    default_approver_by_permission_id: dict[int, _ApproverResolution]


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
    direct_manager_resolution = _direct_manager_approver_resolution(user, resolver)
    default_approver_by_app_id = _app_default_approver_by_app_id(
        apps,
        user,
        resolver,
    )
    default_approver_by_group_id = _approval_rule_approvers_by_group_id(
        authorization_groups,
        resolver,
        direct_manager_resolution,
    )
    default_approver_by_permission_id = _approval_rule_approvers_by_permission_id(
        permissions,
        resolver,
        direct_manager_resolution,
    )
    approver_candidates = _approver_candidates(
        approver_users,
        (
            direct_manager_resolution,
            *default_approver_by_app_id.values(),
            *default_approver_by_group_id.values(),
            *default_approver_by_permission_id.values(),
        ),
    )
    return {
        "apps": [
            _catalog_app_item(app, default_approver_by_app_id[app.id])
            for app in apps
        ],
        "authorization_groups": [
            _catalog_authorization_group_item(
                group,
                default_approver_by_group_id.get(group.id) or default_approver_by_app_id[
                    group.app_id
                ],
            )
            for group in authorization_groups
        ],
        "permission_groups": _catalog_permission_groups(
            permissions,
            _PermissionCatalogContext(
                scope_options_by_app_id=scope_options_by_app_id,
                default_approver_by_app_id=default_approver_by_app_id,
                default_approver_by_permission_id=default_approver_by_permission_id,
            ),
        ),
        "ungrouped_permissions": [
            _catalog_permission_item(
                permission,
                scope_options_by_app_id,
                default_approver_by_permission_id.get(permission.id) or default_approver_by_app_id[
                    permission.app_id
                ],
            )
            for permission in permissions
            if permission.group is None
        ],
        "approver_options": [_approver_option(user) for user in approver_candidates],
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
    approver_resolution: _ApproverResolution,
) -> dict[str, JsonValue]:
    return {
        "id": app.id,
        "app_key": app.app_key,
        "name": app.name,
        "description": app.description,
        "catalog_version": app.catalog_version,
        "default_approver_user_ids": _json_strings(approver_resolution.user_ids),
        "approver_resolution_status": approver_resolution.status,
    }


def _catalog_authorization_group_item(
    group: AuthorizationGroup,
    approver_resolution: _ApproverResolution,
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
        "default_approver_user_ids": _json_strings(approver_resolution.user_ids),
        "approver_resolution_status": approver_resolution.status,
    }


def _catalog_permission_groups(
    permissions: tuple[Permission, ...],
    context: _PermissionCatalogContext,
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
            context,
        )
        for group in children_by_parent.get(None, [])
    ]


def _catalog_group_item(
    group: PermissionGroup,
    children_by_parent: dict[int | None, list[PermissionGroup]],
    permissions_by_group: dict[int, list[Permission]],
    context: _PermissionCatalogContext,
) -> dict[str, JsonValue]:
    permission_items: list[JsonValue] = [
        _catalog_permission_item(
            permission,
            context.scope_options_by_app_id,
            context.default_approver_by_permission_id.get(permission.id)
            or context.default_approver_by_app_id[permission.app_id],
        )
        for permission in permissions_by_group.get(group.id, [])
    ]
    children: list[JsonValue] = [
        _catalog_group_item(
            child,
            children_by_parent,
            permissions_by_group,
            context,
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
    approver_resolution: _ApproverResolution,
) -> dict[str, JsonValue]:
    group = permission.group
    scopes = _permission_scope_options(permission, scope_options_by_app_id)
    scope_items: list[JsonValue] = []
    scope_items.extend(scopes)
    return {
        "id": permission.id,
        "app_key": permission.app.app_key,
        "type": "permission",
        "key": permission.key,
        "name": permission.name,
        "description": permission.description,
        "group_key": "" if group is None else group.key,
        "scopes": scope_items,
        "default_approver_user_ids": _json_strings(approver_resolution.user_ids),
        "approver_resolution_status": approver_resolution.status,
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
    options: list[dict[str, JsonValue]] = []
    for scope in scope_options_by_app_id.get(permission.app_id, []):
        scope_key = scope["key"]
        if isinstance(scope_key, str) and _permission_supports_scope(permission, scope_key):
            options.append(scope)
    return options


def _permission_supports_scope(permission: Permission, scope_key: str) -> bool:
    supported_scopes = permission.supported_scopes
    return isinstance(supported_scopes, list) and scope_key in supported_scopes


def _active_approver_users() -> tuple[UserMirror, ...]:
    return tuple(
        UserMirror.objects.filter(status=USER_STATUS_ACTIVE).order_by("authentik_user_id"),
    )


def _approver_candidates(
    approver_users: tuple[UserMirror, ...],
    resolutions: tuple[_ApproverResolution, ...],
) -> tuple[UserMirror, ...]:
    # 只暴露与本次申请相关的候选审批人(直属主管/规则审批人/App owner),
    # 不把全公司在职目录发给任意登录员工。
    candidate_user_ids: set[str] = set()
    for resolution in resolutions:
        candidate_user_ids.update(resolution.user_ids)
    return tuple(
        user for user in approver_users if user.authentik_user_id in candidate_user_ids
    )


def _approver_option(user: UserMirror) -> dict[str, JsonValue]:
    # 只返回展示所需的最小字段, 不泄漏邮箱和部门。
    return {
        "user_id": user.authentik_user_id,
        "name": user.name,
    }


def _app_default_approver_by_app_id(
    apps: tuple[App, ...],
    user: UserMirror,
    resolver: _ApproverResolver,
) -> dict[int, _ApproverResolution]:
    app_ids = tuple(app.id for app in apps)
    owner_user_ids_by_app_id = _owner_user_ids_by_app_id(app_ids)
    manager_user_ids = resolver.resolve((user.manager_userid,))
    return {
        app.id: _ApproverResolution(
            user_ids=manager_user_ids
            or resolver.resolve(owner_user_ids_by_app_id.get(app.id, ())),
            status=APPROVER_RESOLUTION_DEFAULT_POLICY,
        )
        for app in apps
    }


def _direct_manager_approver_resolution(
    user: UserMirror,
    resolver: _ApproverResolver,
) -> _ApproverResolution:
    manager_user_ids = resolver.resolve((user.manager_userid,))
    if manager_user_ids:
        return _ApproverResolution(
            user_ids=manager_user_ids,
            status=APPROVER_RESOLUTION_RESOLVED_BY_DIRECT_MANAGER,
        )
    return _ApproverResolution(
        user_ids=(),
        status=APPROVER_RESOLUTION_DIRECT_MANAGER_MISSING,
    )


def _owner_user_ids_by_app_id(app_ids: tuple[int, ...]) -> dict[int, tuple[str, ...]]:
    owner_user_ids_by_app_id: dict[int, list[str]] = {app_id: [] for app_id in app_ids}
    membership_rows = AppMembership.objects.filter(
        app_id__in=app_ids,
        role="owner",
        is_active=True,
    ).order_by("app_id", "user_id").values_list("app_id", "user_id")
    for raw_app_id, raw_user_id in cast("Iterable[tuple[object, object]]", membership_rows):
        app_id = cast("int", raw_app_id)
        user_id = cast("str", raw_user_id)
        owner_user_ids_by_app_id.setdefault(app_id, []).append(user_id)
    return {
        app_id: tuple(owner_user_ids)
        for app_id, owner_user_ids in owner_user_ids_by_app_id.items()
    }


def _approval_rule_approvers_by_group_id(
    groups: tuple[AuthorizationGroup, ...],
    resolver: _ApproverResolver,
    direct_manager_resolution: _ApproverResolution,
) -> dict[int, _ApproverResolution]:
    group_ids = tuple(group.id for group in groups)
    if not group_ids:
        return {}
    defaults: dict[int, _ApproverResolution] = {}
    raw_managed_group_ids = AuthorizationGroupGrant.objects.filter(
        authorization_group_id__in=group_ids,
        is_active=True,
        scope_key=MANAGED_USERS_SCOPE,
    ).values_list("authorization_group_id", flat=True)
    managed_group_ids = tuple(
        cast("int", group_id)
        for group_id in cast("Iterable[object]", raw_managed_group_ids)
    )
    for group_id in managed_group_ids:
        defaults[group_id] = direct_manager_resolution
    rule_rows = ApprovalRule.objects.filter(
        authorization_group_id__in=group_ids,
        is_active=True,
    ).order_by("authorization_group_id", "id").values_list(
        "authorization_group_id",
        "approver_userids",
    )
    for raw_group_id, approver_userids in cast("Iterable[tuple[object, object]]", rule_rows):
        group_id = cast("int", raw_group_id)
        if group_id in defaults:
            continue
        approver_user_ids = resolver.resolve(approver_userids)
        if approver_user_ids:
            defaults[group_id] = _ApproverResolution(
                user_ids=approver_user_ids,
                status=APPROVER_RESOLUTION_DEFAULT_POLICY,
            )
    return defaults


def _approval_rule_approvers_by_permission_id(
    permissions: tuple[Permission, ...],
    resolver: _ApproverResolver,
    direct_manager_resolution: _ApproverResolution,
) -> dict[int, _ApproverResolution]:
    permission_ids = tuple(permission.id for permission in permissions)
    if not permission_ids:
        return {}
    defaults: dict[int, _ApproverResolution] = {
        permission.id: direct_manager_resolution
        for permission in permissions
        if _permission_supports_scope(permission, MANAGED_USERS_SCOPE)
    }
    rule_rows = ApprovalRule.objects.filter(
        permission_id__in=permission_ids,
        is_active=True,
    ).order_by("permission_id", "id").values_list("permission_id", "approver_userids")
    for raw_permission_id, approver_userids in cast(
        "Iterable[tuple[object, object]]",
        rule_rows,
    ):
        permission_id = cast("int", raw_permission_id)
        if permission_id in defaults:
            continue
        approver_user_ids = resolver.resolve(approver_userids)
        if approver_user_ids:
            defaults[permission_id] = _ApproverResolution(
                user_ids=approver_user_ids,
                status=APPROVER_RESOLUTION_DEFAULT_POLICY,
            )
    return defaults


class _ApproverResolver:
    def __init__(self, users: tuple[UserMirror, ...]) -> None:
        self._user_id_by_authentik_user_id: dict[str, str] = {
            user.authentik_user_id: user.authentik_user_id for user in users
        }
        self._user_id_by_dingtalk_userid: dict[str, str] = {
            user.dingtalk_userid: user.authentik_user_id
            for user in users
            if user.dingtalk_userid
        }

    def resolve(self, raw_user_ids: object) -> tuple[str, ...]:
        if not isinstance(raw_user_ids, (list, tuple)):
            return ()
        resolved_user_ids: list[str] = []
        seen: set[str] = set()
        for raw_user_id in cast("list[object] | tuple[object, ...]", raw_user_ids):
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
