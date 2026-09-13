from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.db.models import Q
from django.utils import timezone

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import AppScope, AuthorizationGroupGrant
from easyauth.connectors.base import DesiredState, DesiredUserProfile
from easyauth.connectors.models import ConnectorMapping
from easyauth.grants.models import GRANT_STATUS_ACTIVE, AccessGrantGroup, AccessGrantPermission

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.connectors.models import ConnectorInstance


def build_desired_state(instance: ConnectorInstance) -> DesiredState:
    """构建只包含有效成员的投影, 并与权限查询共用 active 组与期限口径。"""
    now = timezone.now()
    mappings = tuple(
        ConnectorMapping.objects.filter(instance=instance).select_related("authorization_group"),
    )
    active_mappings = _active_connector_mappings(mappings)
    # 2026-09-07 事故: 直接权限覆盖组所需权限时也投影, 不能只看 AccessGrantGroup。
    # (a) 当前授权含该映射组的未过期成员; 或
    # (b) required(G) 非空且包含于用户有效权限(组成员展开与直接授权, 口径同 grants.query)。
    user_group_refs, profiles = _project_users_by_effective_permissions(
        instance,
        active_mappings,
        now,
    )
    return DesiredState(
        user_groups={user_id: frozenset(refs) for user_id, refs in user_group_refs.items()},
        profiles=profiles,
        managed_group_refs=frozenset(mapping.external_ref for mapping in mappings),
        # external_ref 是不可变外部组 ID, 不支持按名称自动创建; 字段保留为空以消除死配置假成功。
        auto_create_group_refs=frozenset(),
    )


def _active_connector_mappings(
    mappings: tuple[ConnectorMapping, ...],
) -> tuple[ConnectorMapping, ...]:
    # 仅 active 且未 tombstone 的映射参与扩权; tombstone/缺组映射仍进入 managed 以便收缩清理。
    return tuple(
        mapping
        for mapping in mappings
        if (
            not mapping.tombstoned
            and mapping.authorization_group is not None
            and mapping.authorization_group.is_active
        )
    )


def _project_users_by_effective_permissions(
    instance: ConnectorInstance,
    active_mappings: tuple[ConnectorMapping, ...],
    now: datetime,
) -> tuple[dict[str, set[str]], dict[str, DesiredUserProfile]]:
    user_group_refs: dict[str, set[str]] = {}
    profiles: dict[str, DesiredUserProfile] = {}
    if instance.tombstoned:
        return user_group_refs, profiles
    active_scope_keys = _active_scope_keys(instance.app_id)
    required_by_group_id = _required_permission_pairs_by_group(
        app_id=instance.app_id,
        active_scope_keys=active_scope_keys,
    )
    users_by_id, memberships_by_user, effective_by_user = _user_effective_permission_index(
        instance,
        now=now,
        active_scope_keys=active_scope_keys,
        required_by_group_id=required_by_group_id,
    )
    for mapping in active_mappings:
        group_id = mapping.authorization_group_id
        if group_id is None:
            continue
        required = required_by_group_id.get(group_id, set())
        for user_id, user in users_by_id.items():
            via_membership = group_id in memberships_by_user.get(user_id, set())
            via_coverage = bool(required) and required <= effective_by_user.get(user_id, set())
            if not (via_membership or via_coverage):
                continue
            refs = user_group_refs.setdefault(user_id, set())
            refs.add(mapping.external_ref)
            profiles[user_id] = DesiredUserProfile(
                user_id=user.authentik_user_id,
                name=user.name,
                email=user.email,
            )
    return user_group_refs, profiles


def _active_scope_keys(app_id: int) -> set[str]:
    return set(
        AppScope.objects.filter(app_id=app_id, is_active=True).values_list("key", flat=True),
    )


def _supported_scope_keys(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items = cast("list[object]", value)
    return [scope for scope in items if isinstance(scope, str)]


def _scope_key_is_effective(
    scope_key: str,
    supported_scopes: object,
    active_scope_keys: set[str],
) -> bool:
    return scope_key in active_scope_keys and scope_key in _supported_scope_keys(supported_scopes)


def _required_permission_pairs_by_group(
    *,
    app_id: int,
    active_scope_keys: set[str],
) -> dict[int, set[tuple[str, str]]]:
    links = AuthorizationGroupGrant.objects.select_related("permission").filter(
        authorization_group__app_id=app_id,
        authorization_group__is_active=True,
        is_active=True,
        permission__is_active=True,
        permission__deprecated_at__isnull=True,
    )
    required_by_group_id: dict[int, set[tuple[str, str]]] = {}
    for link in links:
        if not _scope_key_is_effective(
            link.scope_key,
            link.permission.supported_scopes,
            active_scope_keys,
        ):
            continue
        required_by_group_id.setdefault(link.authorization_group_id, set()).add(
            (link.permission.key, link.scope_key),
        )
    return required_by_group_id


def _user_effective_permission_index(
    instance: ConnectorInstance,
    *,
    now: datetime,
    active_scope_keys: set[str],
    required_by_group_id: dict[int, set[tuple[str, str]]],
) -> tuple[dict[str, UserMirror], dict[str, set[int]], dict[str, set[tuple[str, str]]]]:
    users_by_id: dict[str, UserMirror] = {}
    memberships_by_user: dict[str, set[int]] = {}
    effective_by_user: dict[str, set[tuple[str, str]]] = {}
    current_grant = Q(
        grant__app_id=instance.app_id,
        grant__is_current=True,
        grant__status=GRANT_STATUS_ACTIVE,
        grant__user__status=USER_STATUS_ACTIVE,
    )
    membership_rows = (
        AccessGrantGroup.objects.filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now),
            current_grant,
            authorization_group__is_active=True,
        )
        .select_related("grant__user")
        .order_by("id")
    )
    for row in membership_rows:
        user = row.grant.user
        user_id = user.authentik_user_id
        users_by_id[user_id] = user
        memberships_by_user.setdefault(user_id, set()).add(row.authorization_group_id)
        group_pairs = required_by_group_id.get(row.authorization_group_id)
        if group_pairs:
            effective_by_user.setdefault(user_id, set()).update(group_pairs)
    direct_rows = AccessGrantPermission.objects.select_related("permission", "grant__user").filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now),
        current_grant,
        permission__is_active=True,
        permission__deprecated_at__isnull=True,
    )
    for row in direct_rows:
        if not _scope_key_is_effective(
            row.scope_key,
            row.permission.supported_scopes,
            active_scope_keys,
        ):
            continue
        user = row.grant.user
        user_id = user.authentik_user_id
        users_by_id[user_id] = user
        effective_by_user.setdefault(user_id, set()).add((row.permission.key, row.scope_key))
    return users_by_id, memberships_by_user, effective_by_user
