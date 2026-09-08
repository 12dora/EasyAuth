"""维护每个应用的平台内置授权组 super_admin。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast, final

from django.db import transaction

from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.applications.models.constants import BUILTIN_SUPER_ADMIN_GROUP_KEY

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable

    from easyauth.applications.models.constants import JsonValue

RESERVED_AUTHORIZATION_GROUP_REASON: Final = "reserved_authorization_group"
BUILTIN_SUPER_ADMIN_KIND: Final = "role"
BUILTIN_SUPER_ADMIN_NAME: Final = "超级管理员"
BUILTIN_SUPER_ADMIN_NAME_EN: Final = "Super administrator"
BUILTIN_SUPER_ADMIN_DESCRIPTION: Final = "拥有该应用的全部权限。"
BUILTIN_SUPER_ADMIN_DESCRIPTION_EN: Final = "Holds every permission of this app."

__all__ = [
    "BUILTIN_SUPER_ADMIN_DESCRIPTION",
    "BUILTIN_SUPER_ADMIN_DESCRIPTION_EN",
    "BUILTIN_SUPER_ADMIN_GROUP_KEY",
    "BUILTIN_SUPER_ADMIN_KIND",
    "BUILTIN_SUPER_ADMIN_NAME",
    "BUILTIN_SUPER_ADMIN_NAME_EN",
    "RESERVED_AUTHORIZATION_GROUP_REASON",
    "ReservedAuthorizationGroupCollisionError",
    "ensure_builtin_super_admin",
    "is_reserved_authorization_group_key",
    "reserved_authorization_group_collision_message",
    "super_admin_grant_targets",
]


@final
class ReservedAuthorizationGroupCollisionError(RuntimeError):
    """应用已有非内置的 reserved key 授权组, 禁止静默接管。"""

    app_key: str

    def __init__(self, app_key: str) -> None:
        self.app_key = app_key
        super().__init__(reserved_authorization_group_collision_message(app_key))


def reserved_authorization_group_collision_message(app_key: str) -> str:
    return (
        f"应用 {app_key} 已存在 key={BUILTIN_SUPER_ADMIN_GROUP_KEY} 的非平台内置授权组。"
        "请先手工处理该组后再继续。"
    )


def is_reserved_authorization_group_key(key: str) -> bool:
    return key == BUILTIN_SUPER_ADMIN_GROUP_KEY


def super_admin_grant_targets(
    *,
    permission_ids_and_scopes: Iterable[tuple[int, object]],
    active_scope_keys: Collection[str],
) -> frozenset[tuple[int, str]]:
    """计算 super_admin 应持有的 (permission_id, scope_key)。

    每个 active、未废弃权限的 supported_scopes, 与该应用当前 active AppScope 求交。
    """
    targets: set[tuple[int, str]] = set()
    for permission_id, supported_scopes in permission_ids_and_scopes:
        for scope_key in _supported_scope_keys(supported_scopes):
            if scope_key in active_scope_keys:
                targets.add((permission_id, scope_key))
    return frozenset(targets)


@transaction.atomic
def ensure_builtin_super_admin(app: App) -> AuthorizationGroup:
    """幂等写入平台内置 super_admin 授权组及其 grant, 并清掉过期 grant。

    只接管 is_builtin=True 的组; 不会改 catalog_version, 也不会改写 grant 上已有的
    managed_scope_policy 覆盖。
    """
    group = _upsert_super_admin_group(app)
    _sync_super_admin_grants(app, group)
    return group


def _upsert_super_admin_group(app: App) -> AuthorizationGroup:
    group = (
        AuthorizationGroup.objects.select_for_update()
        .filter(app=app, key=BUILTIN_SUPER_ADMIN_GROUP_KEY)
        .first()
    )
    if group is None:
        group = AuthorizationGroup(
            app=app,
            key=BUILTIN_SUPER_ADMIN_GROUP_KEY,
            is_builtin=True,
        )
    elif not group.is_builtin:
        raise ReservedAuthorizationGroupCollisionError(app.app_key)
    group.kind = BUILTIN_SUPER_ADMIN_KIND
    group.name = BUILTIN_SUPER_ADMIN_NAME
    group.name_en = BUILTIN_SUPER_ADMIN_NAME_EN
    group.description = BUILTIN_SUPER_ADMIN_DESCRIPTION
    group.description_en = BUILTIN_SUPER_ADMIN_DESCRIPTION_EN
    group.requestable = False
    group.is_active = True
    group.is_builtin = True
    group.full_clean()
    group.save()
    return group


def _sync_super_admin_grants(app: App, group: AuthorizationGroup) -> None:
    # 只对齐 grant 成员与 is_active; 不创建、不删除、不改写 ManagedScopePolicy 覆盖。
    desired = _desired_grant_targets(app)
    existing = {
        (grant.permission_id, grant.scope_key): grant
        for grant in AuthorizationGroupGrant.objects.filter(authorization_group=group)
    }
    permission_by_id = {
        permission.id: permission
        for permission in Permission.objects.filter(id__in={item[0] for item in desired})
    }
    for permission_id, scope_key in desired:
        grant = existing.get((permission_id, scope_key))
        if grant is None:
            grant = AuthorizationGroupGrant(
                authorization_group=group,
                permission=permission_by_id[permission_id],
                scope_key=scope_key,
                is_active=True,
            )
            grant.full_clean()
            grant.save()
            continue
        if grant.is_active:
            continue
        grant.is_active = True
        grant.full_clean()
        grant.save(update_fields=["is_active", "updated_at"])
    for fingerprint, grant in existing.items():
        if fingerprint in desired or not grant.is_active:
            continue
        grant.is_active = False
        grant.full_clean()
        grant.save(update_fields=["is_active", "updated_at"])


def _desired_grant_targets(app: App) -> frozenset[tuple[int, str]]:
    active_scope_keys = set(
        AppScope.objects.filter(app=app, is_active=True).values_list("key", flat=True),
    )
    permission_ids_and_scopes: list[tuple[int, object]] = [
        (permission.id, permission.supported_scopes)
        for permission in Permission.objects.filter(
            app=app,
            is_active=True,
            deprecated_at__isnull=True,
        )
    ]
    return super_admin_grant_targets(
        permission_ids_and_scopes=permission_ids_and_scopes,
        active_scope_keys=active_scope_keys,
    )


def _supported_scope_keys(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    items = cast("list[JsonValue]", value)
    return tuple(item for item in items if isinstance(item, str))
