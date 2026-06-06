from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from easyauth.admin_console.credentials import OneTimeSecret
from easyauth.admin_console.permission_templates import PermissionTemplateConsoleResult
from easyauth.admin_console.query_tester import PermissionQueryTestResult
from easyauth.applications.configuration import (
    ConfigurationReadiness,
    configuration_readiness_for_app,
)
from easyauth.applications.models import (
    App,
    AppCredential,
    ApprovalRule,
    OAuthClientBinding,
    Permission,
    PermissionGroup,
    Role,
    RolePermission,
)
from easyauth.applications.ownership import ConsoleActor, apps_visible_to_actor, can_manage_app

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.models import QuerySet


@dataclass(frozen=True, slots=True)
class MatrixCell:
    role: Role
    checked: bool


@dataclass(frozen=True, slots=True)
class MatrixRow:
    permission: Permission
    group_label: str
    cells: tuple[MatrixCell, ...]


@dataclass(frozen=True, slots=True)
class PermissionGroupTreeRow:
    group: PermissionGroup
    path: str
    permission_keys: tuple[str, ...]


type AppDetailContextValue = (
    App
    | bool
    | set[int]
    | tuple[MatrixRow, ...]
    | tuple[Role, ...]
    | tuple[PermissionGroupTreeRow, ...]
    | tuple[AppCredential, ...]
    | tuple[OAuthClientBinding, ...]
    | list[App]
    | ConfigurationReadiness
    | QuerySet[PermissionGroup]
    | OneTimeSecret
    | PermissionTemplateConsoleResult
    | PermissionQueryTestResult
    | None
)


def app_detail_context(
    actor: ConsoleActor,
    app: App,
    *,
    one_time_secret: OneTimeSecret | None,
    template_result: PermissionTemplateConsoleResult | None,
    query_test_result: PermissionQueryTestResult | None,
) -> dict[str, AppDetailContextValue]:
    roles = tuple(Role.objects.filter(app=app).order_by("key"))
    permissions = tuple(
        Permission.objects.select_related("group")
        .filter(app=app, is_active=True)
        .order_by("group__display_order", "group__key", "key"),
    )
    return {
        "app": app,
        "approval_rule_role_ids": _approval_rule_role_ids(app),
        "can_manage": can_manage_app(actor, app),
        "credentials": tuple(AppCredential.objects.filter(app=app).order_by("id")),
        "matrix_rows": _matrix_rows(roles, permissions),
        "oauth_bindings": tuple(
            OAuthClientBinding.objects.select_related("oauth_application")
            .filter(app=app)
            .order_by("id"),
        ),
        "one_time_secret": one_time_secret,
        "permission_groups": PermissionGroup.objects.filter(app=app, is_active=True).order_by(
            "depth",
            "display_order",
            "key",
        ),
        "permission_group_tree_rows": _permission_group_tree_rows(app),
        "query_test_result": query_test_result,
        "readiness": configuration_readiness_for_app(app),
        "roles": roles,
        "template_result": template_result,
        "visible_apps": apps_visible_to_actor(actor),
    }


def _matrix_rows(
    roles: Sequence[Role],
    permissions: Sequence[Permission],
) -> tuple[MatrixRow, ...]:
    links = _role_permission_pairs(roles, permissions)
    return tuple(
        MatrixRow(
            permission=permission,
            group_label=_permission_group_label(permission),
            cells=tuple(
                MatrixCell(
                    role=role,
                    checked=(role.id, permission.id) in links,
                )
                for role in roles
            ),
        )
        for permission in permissions
    )


def _role_permission_pairs(
    roles: Sequence[Role],
    permissions: Sequence[Permission],
) -> set[tuple[int, int]]:
    role_ids = [role.id for role in roles]
    permission_ids = [permission.id for permission in permissions]
    return {
        (link.role_id, link.permission_id)
        for link in RolePermission.objects.filter(
            role_id__in=role_ids,
            permission_id__in=permission_ids,
        )
    }


def _approval_rule_role_ids(app: App) -> set[int]:
    return set(
        ApprovalRule.objects.filter(app=app, is_active=True, role__isnull=False).values_list(
            "role_id",
            flat=True,
        ),
    )


def _permission_group_label(permission: Permission) -> str:
    group = permission.group
    if group is None:
        return "未归类"
    return group.key


def _permission_group_tree_rows(app: App) -> tuple[PermissionGroupTreeRow, ...]:
    groups = tuple(
        PermissionGroup.objects.select_related("parent")
        .filter(app=app, is_active=True)
        .order_by("depth", "display_order", "key"),
    )
    permission_keys_by_group = _permission_keys_by_group(app)
    return tuple(
        PermissionGroupTreeRow(
            group=group,
            path=_permission_group_path(group),
            permission_keys=tuple(permission_keys_by_group.get(group.id, ())),
        )
        for group in groups
    )


def _permission_keys_by_group(app: App) -> dict[int, list[str]]:
    permission_keys_by_group: dict[int, list[str]] = {}
    permissions = Permission.objects.select_related("group").filter(
        app=app,
        is_active=True,
        group__isnull=False,
    )
    for permission in permissions.order_by("key"):
        group = permission.group
        if group is not None:
            permission_keys_by_group.setdefault(group.id, []).append(permission.key)
    return permission_keys_by_group


def _permission_group_path(group: PermissionGroup) -> str:
    keys = [group.key]
    parent = group.parent
    while parent is not None:
        keys.append(parent.key)
        parent = parent.parent
    return " / ".join(reversed(keys))
