"""门户申请目录的查询与条目序列化: 应用、授权组、权限树与 scope 选项。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
    PermissionGroup,
)
from easyauth.portal.request_catalog_approvers import (
    ApproverResolution,
    RequestCatalogApprovers,
    approver_option,
    json_strings,
)

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue


@dataclass(frozen=True, slots=True)
class RequestCatalogData:
    apps: tuple[App, ...]
    authorization_groups: tuple[AuthorizationGroup, ...]
    permissions: tuple[Permission, ...]
    scope_options_by_app_id: dict[int, list[dict[str, JsonValue]]]
    grants_by_group_id: dict[int, tuple[AuthorizationGroupGrant, ...]]


@dataclass(frozen=True, slots=True)
class _PermissionCatalogContext:
    scope_options_by_app_id: dict[int, list[dict[str, JsonValue]]]
    default_approver_by_app_id: dict[int, ApproverResolution]
    default_approver_by_permission_id: dict[int, ApproverResolution]


def load_request_catalog_data() -> RequestCatalogData:
    apps = tuple(App.objects.filter(is_active=True).order_by("app_key"))
    scope_options_by_app_id = _scope_options_by_app_id(tuple(app.id for app in apps))
    authorization_groups = _request_catalog_authorization_groups()
    permissions = tuple(
        permission
        for permission in _request_catalog_permissions()
        if _permission_scope_options(permission, scope_options_by_app_id)
    )
    return RequestCatalogData(
        apps=apps,
        authorization_groups=authorization_groups,
        permissions=permissions,
        scope_options_by_app_id=scope_options_by_app_id,
        grants_by_group_id=_grants_by_group_id(authorization_groups),
    )


def serialize_request_catalog(
    catalog: RequestCatalogData,
    approvers: RequestCatalogApprovers,
) -> dict[str, JsonValue]:
    return {
        "apps": [
            _catalog_app_item(app, approvers.default_approver_by_app_id[app.id])
            for app in catalog.apps
        ],
        "authorization_groups": [
            _catalog_authorization_group_item(
                group,
                _group_approver_resolution(group, approvers),
                catalog.grants_by_group_id.get(group.id, ()),
            )
            for group in catalog.authorization_groups
        ],
        "permission_groups": _catalog_permission_groups(
            catalog.permissions,
            _PermissionCatalogContext(
                scope_options_by_app_id=catalog.scope_options_by_app_id,
                default_approver_by_app_id=approvers.default_approver_by_app_id,
                default_approver_by_permission_id=approvers.default_approver_by_permission_id,
            ),
        ),
        "ungrouped_permissions": [
            _catalog_permission_item(
                permission,
                catalog.scope_options_by_app_id,
                _permission_approver_resolution(permission, approvers),
            )
            for permission in catalog.permissions
            if permission.group is None
        ],
        "approver_options": [approver_option(user) for user in approvers.approver_candidates],
    }


def _group_approver_resolution(
    group: AuthorizationGroup,
    approvers: RequestCatalogApprovers,
) -> ApproverResolution:
    return (
        approvers.default_approver_by_group_id.get(group.id)
        or approvers.default_approver_by_app_id[group.app_id]
    )


def _permission_approver_resolution(
    permission: Permission,
    approvers: RequestCatalogApprovers,
) -> ApproverResolution:
    return (
        approvers.default_approver_by_permission_id.get(permission.id)
        or approvers.default_approver_by_app_id[permission.app_id]
    )


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
    approver_resolution: ApproverResolution,
) -> dict[str, JsonValue]:
    return {
        "id": app.id,
        "app_key": app.app_key,
        "name": app.name,
        "alias": app.alias,
        "description": app.description,
        "catalog_version": app.catalog_version,
        "default_approver_user_ids": json_strings(approver_resolution.user_ids),
        "approver_resolution_status": approver_resolution.status,
    }


def _catalog_authorization_group_item(
    group: AuthorizationGroup,
    approver_resolution: ApproverResolution,
    grants: tuple[AuthorizationGroupGrant, ...],
) -> dict[str, JsonValue]:
    # grants 供门户在选中权限组后联动展示该组覆盖的权限范围(展示态, 不参与直接权限提交)。
    grant_items: list[JsonValue] = [
        {"permission_key": grant.permission.key, "scope_key": grant.scope_key} for grant in grants
    ]
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
        "requires_approval": True,
        "default_approver_user_ids": json_strings(approver_resolution.user_ids),
        "approver_resolution_status": approver_resolution.status,
        "grants": grant_items,
    }


def _grants_by_group_id(
    groups: tuple[AuthorizationGroup, ...],
) -> dict[int, tuple[AuthorizationGroupGrant, ...]]:
    group_ids = tuple(group.id for group in groups)
    if not group_ids:
        return {}
    grants_by_group_id: dict[int, list[AuthorizationGroupGrant]] = {}
    grant_rows = (
        AuthorizationGroupGrant.objects.filter(
            authorization_group_id__in=group_ids,
            is_active=True,
        )
        .select_related("permission")
        .order_by("authorization_group_id", "permission__key", "scope_key")
    )
    for grant in grant_rows:
        grants_by_group_id.setdefault(grant.authorization_group_id, []).append(grant)
    return {group_id: tuple(grants) for group_id, grants in grants_by_group_id.items()}


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
        "name_en": group.name_en,
        "description": group.description,
        "description_en": group.description_en,
        "depth": group.depth,
        "children": children,
        "permissions": permission_items,
    }


def _catalog_permission_item(
    permission: Permission,
    scope_options_by_app_id: dict[int, list[dict[str, JsonValue]]],
    approver_resolution: ApproverResolution,
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
        "name_en": permission.name_en,
        "description": permission.description,
        "description_en": permission.description_en,
        "group_key": "" if group is None else group.key,
        "scopes": scope_items,
        "default_approver_user_ids": json_strings(approver_resolution.user_ids),
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
            {
                "key": scope.key,
                "name": scope.name,
                "name_en": scope.name_en,
                "description": scope.description,
                "description_en": scope.description_en,
            },
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
