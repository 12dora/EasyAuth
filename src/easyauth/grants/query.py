from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, cast

from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.accounts.status import parse_user_status
from easyauth.applications.models import App, AppScope, AuthorizationGroupGrant
from easyauth.grants.catalog_names import resolve_catalog_display_names
from easyauth.grants.managed_users import (
    MANAGED_USERS_SCOPE,
    ManagedUsersDirectoryCache,
    resolve_managed_users,
)
from easyauth.grants.models import (
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from easyauth.grants.query_types import ResolvedManagedUsers  # noqa: TC001 - 对外重导出类型。
from easyauth.grants.status import parse_grant_status

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

type UserSelector = UserMirror | str


@dataclass(frozen=True, slots=True)
class GroupSnapshot:
    key: str
    kind: str
    name: str
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class ExpandedGrant:
    permission: str
    scope: str
    source_type: str
    source_key: str
    expires_at: datetime | None
    resolved: ResolvedManagedUsers | None = None
    # 目录展示名不参与相等比较: 既有调用方仍按 key 构造 ExpandedGrant。
    permission_name: str = field(default="", compare=False)
    permission_name_en: str = field(default="", compare=False)
    scope_name: str = field(default="", compare=False)
    scope_name_en: str = field(default="", compare=False)


@dataclass(frozen=True, slots=True)
class PermissionSnapshot:
    user_id: str
    app_key: str
    groups: tuple[GroupSnapshot, ...]
    grants: tuple[ExpandedGrant, ...]
    grant_version: int
    catalog_version: int
    snapshot_version: str


def resolve_user_permissions(
    *,
    user: UserSelector,
    app: App,
    managed_users_cache: ManagedUsersDirectoryCache | None = None,
) -> PermissionSnapshot:
    resolved_user = _resolve_user(user)
    user_id = _user_id(user)
    if resolved_user is None:
        return _empty_snapshot(user_id=user_id, app=app, grant_version=0)

    latest_grant = _latest_grant(resolved_user, app)
    grant_version = 0 if latest_grant is None else latest_grant.version
    if latest_grant is None or not _grant_has_effective_permissions(resolved_user, latest_grant):
        return _empty_snapshot(user_id=user_id, app=app, grant_version=grant_version)
    return snapshot_for_grant(latest_grant, managed_users_cache=managed_users_cache)


def snapshot_for_grant(
    grant: AccessGrant,
    *,
    managed_users_cache: ManagedUsersDirectoryCache | None = None,
    now: datetime | None = None,
) -> PermissionSnapshot:
    cache: ManagedUsersDirectoryCache = {} if managed_users_cache is None else managed_users_cache
    return _grant_snapshot(
        user_id=grant.user.authentik_user_id,
        app=grant.app,
        grant=grant,
        directory_cache=cache,
        now=timezone.now() if now is None else now,
    )


def _resolve_user(user: UserSelector) -> UserMirror | None:
    match user:
        case UserMirror() as user_model:
            return user_model
        case str() as user_id:
            return UserMirror.objects.filter(authentik_user_id=user_id).first()


def _user_id(user: UserSelector) -> str:
    match user:
        case UserMirror() as user_model:
            return user_model.authentik_user_id
        case str() as user_id:
            return user_id


def _latest_grant(user: UserMirror, app: App) -> AccessGrant | None:
    return AccessGrant.objects.filter(user=user, app=app).order_by("-version", "-id").first()


def _grant_has_effective_permissions(user: UserMirror, grant: AccessGrant) -> bool:
    match parse_user_status(user.status):
        case "active":
            pass
        case "disabled" | "departed":
            return False

    if not grant.is_current:
        return False

    match parse_grant_status(grant.status):
        case "active":
            return True
        case "revoked" | "expired":
            return False


def _grant_snapshot(
    *,
    user_id: str,
    app: App,
    grant: AccessGrant,
    directory_cache: ManagedUsersDirectoryCache,
    now: datetime,
) -> PermissionSnapshot:
    groups = _group_snapshots(grant, now)
    grants = _expanded_grants(grant, directory_cache, now)
    return PermissionSnapshot(
        user_id=user_id,
        app_key=app.app_key,
        groups=groups,
        grants=grants,
        grant_version=grant.version,
        catalog_version=app.catalog_version,
        snapshot_version=_snapshot_version(
            grant.version,
            app.catalog_version,
            _resolved_digest(grants, groups),
        ),
    )


def _group_snapshots(grant: AccessGrant, now: datetime) -> tuple[GroupSnapshot, ...]:
    snapshots: dict[int, GroupSnapshot] = {}
    for link in _effective_group_links(grant, now):
        previous = snapshots.get(link.authorization_group_id)
        snapshots[link.authorization_group_id] = GroupSnapshot(
            key=link.authorization_group.key,
            kind=link.authorization_group.kind,
            name=link.authorization_group.name,
            expires_at=link.expires_at
            if previous is None
            else _later_expiry(previous.expires_at, link.expires_at),
        )
    return tuple(snapshots.values())


def _later_expiry(left: datetime | None, right: datetime | None) -> datetime | None:
    return None if left is None or right is None else max(left, right)


def _membership_is_effective(expires_at: datetime | None, now: datetime) -> bool:
    return expires_at is None or expires_at > now


def _group_memberships(grant: AccessGrant) -> tuple[AccessGrantGroup, ...]:
    cache = getattr(grant, "_prefetched_objects_cache", {})
    if "grant_groups" in cache:
        rows = cast(
            "Iterable[AccessGrantGroup]",
            grant.grant_groups.all(),  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        )
    else:
        rows = AccessGrantGroup.objects.select_related("authorization_group").filter(grant=grant)
    return tuple(
        sorted(rows, key=lambda link: (link.authorization_group.key, link.source)),
    )


def _permission_memberships(grant: AccessGrant) -> tuple[AccessGrantPermission, ...]:
    cache = getattr(grant, "_prefetched_objects_cache", {})
    if "grant_permissions" in cache:
        rows = cast(
            "Iterable[AccessGrantPermission]",
            grant.grant_permissions.all(),  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        )
    else:
        rows = AccessGrantPermission.objects.select_related("permission").filter(grant=grant)
    return tuple(
        sorted(rows, key=lambda link: (link.permission.key, link.scope_key, link.source)),
    )


def _effective_group_links(grant: AccessGrant, now: datetime) -> tuple[AccessGrantGroup, ...]:
    return tuple(
        link
        for link in _group_memberships(grant)
        if link.authorization_group.is_active and _membership_is_effective(link.expires_at, now)
    )


def _group_expirations(grant: AccessGrant, now: datetime) -> dict[int, datetime | None]:
    group_expirations: dict[int, datetime | None] = {}
    for link in _effective_group_links(grant, now):
        group_id = link.authorization_group_id
        group_expirations[group_id] = (
            _later_expiry(group_expirations[group_id], link.expires_at)
            if group_id in group_expirations
            else link.expires_at
        )
    return group_expirations


def _effective_permission_links(
    grant: AccessGrant,
    now: datetime,
) -> tuple[AccessGrantPermission, ...]:
    return tuple(
        link
        for link in _permission_memberships(grant)
        if link.permission.is_active
        and link.permission.deprecated_at is None
        and _membership_is_effective(link.expires_at, now)
    )


def _expanded_grants(
    grant: AccessGrant,
    directory_cache: ManagedUsersDirectoryCache,
    now: datetime,
) -> tuple[ExpandedGrant, ...]:
    scopes = _active_scope_keys(grant.app)
    expanded = _group_grants(grant, scopes, directory_cache, now) | _direct_grants(
        grant,
        scopes,
        directory_cache,
        now,
    )
    return _with_catalog_names(
        grant.app_id,
        tuple(sorted(expanded, key=_expanded_grant_sort_key)),
    )


def _active_scope_keys(app: App) -> set[str]:
    return set(
        AppScope.objects.filter(app_id=app.id, is_active=True).values_list("key", flat=True),
    )


def _group_grants(
    grant: AccessGrant,
    active_scope_keys: set[str],
    directory_cache: ManagedUsersDirectoryCache,
    now: datetime,
) -> set[ExpandedGrant]:
    group_expirations = _group_expirations(grant, now)
    links = (
        AuthorizationGroupGrant.objects.select_related("authorization_group", "permission")
        .filter(
            authorization_group_id__in=group_expirations,
            authorization_group__is_active=True,
            is_active=True,
            permission__is_active=True,
            permission__deprecated_at__isnull=True,
        )
        .order_by("permission__key", "scope_key", "authorization_group__key")
    )
    expanded: set[ExpandedGrant] = set()
    for link in links:
        if not (
            link.scope_key in active_scope_keys
            and link.scope_key in _supported_scope_keys(link.permission.supported_scopes)
        ):
            continue
        resolved = None
        if link.scope_key == MANAGED_USERS_SCOPE:
            resolved = resolve_managed_users(
                user=grant.user,
                app=grant.app,
                authorization_group_grant=link,
                directory_cache=directory_cache,
            )
            if resolved is None:
                continue
        expanded.add(
            ExpandedGrant(
                permission=link.permission.key,
                scope=link.scope_key,
                source_type="group",
                source_key=link.authorization_group.key,
                expires_at=group_expirations[link.authorization_group_id],
                resolved=resolved,
            ),
        )
    return expanded


def _direct_grants(
    grant: AccessGrant,
    active_scope_keys: set[str],
    directory_cache: ManagedUsersDirectoryCache,
    now: datetime,
) -> set[ExpandedGrant]:
    expanded: dict[tuple[int, str], ExpandedGrant] = {}
    for link in _effective_permission_links(grant, now):
        if not (
            link.scope_key in active_scope_keys
            and link.scope_key in _supported_scope_keys(link.permission.supported_scopes)
        ):
            continue
        resolved = None
        if link.scope_key == MANAGED_USERS_SCOPE:
            resolved = resolve_managed_users(
                user=grant.user,
                app=grant.app,
                directory_cache=directory_cache,
            )
            if resolved is None:
                continue
        identity = (link.permission_id, link.scope_key)
        previous = expanded.get(identity)
        expanded[identity] = ExpandedGrant(
            permission=link.permission.key,
            scope=link.scope_key,
            source_type="direct",
            source_key="",
            expires_at=link.expires_at
            if previous is None
            else _later_expiry(previous.expires_at, link.expires_at),
            resolved=resolved,
        )
    return set(expanded.values())


def _supported_scope_keys(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items = cast("list[object]", value)
    return [scope for scope in items if isinstance(scope, str)]


def _expanded_grant_sort_key(grant: ExpandedGrant) -> tuple[str, str, str, str]:
    return (grant.permission, grant.scope, grant.source_type, grant.source_key)


def _with_catalog_names(
    app_id: int,
    grants: tuple[ExpandedGrant, ...],
) -> tuple[ExpandedGrant, ...]:
    if not grants:
        return grants
    catalog = resolve_catalog_display_names(
        app_id=app_id,
        permission_keys={grant.permission for grant in grants},
        scope_keys={grant.scope for grant in grants},
    )
    return tuple(
        replace(
            grant,
            permission_name=catalog.permissions[grant.permission].name,
            permission_name_en=catalog.permissions[grant.permission].name_en,
            scope_name=catalog.scopes[grant.scope].name,
            scope_name_en=catalog.scopes[grant.scope].name_en,
        )
        for grant in grants
    )


def _empty_snapshot(*, user_id: str, app: App, grant_version: int) -> PermissionSnapshot:
    return PermissionSnapshot(
        user_id=user_id,
        app_key=app.app_key,
        groups=(),
        grants=(),
        grant_version=grant_version,
        catalog_version=app.catalog_version,
        snapshot_version=_snapshot_version(grant_version, app.catalog_version, "0"),
    )


def _snapshot_version(grant_version: int, catalog_version: int, resolved_digest: str) -> str:
    # MANAGED_USERS 有效人员集是查询时动态解析的, 不改变 grant/catalog 版本; 把解析身份的
    # 稳定摘要并入版本, 下属增减才能让下游 etag/缓存失效, 不再服务陈旧集合(BF-2)。
    return f"{grant_version}.{catalog_version}.{resolved_digest}"


def _resolved_digest(
    grants: tuple[ExpandedGrant, ...],
    groups: tuple[GroupSnapshot, ...] = (),
) -> str:
    fact_payloads: list[dict[str, object]] = [
        {
            "expires_at": None if group.expires_at is None else group.expires_at.isoformat(),
            "key": group.key,
            "kind": group.kind,
            "name": group.name,
            "type": "group",
        }
        for group in groups
    ]
    fact_payloads.extend(
        {
            "expires_at": None if grant.expires_at is None else grant.expires_at.isoformat(),
            "permission": grant.permission,
            "scope": grant.scope,
            "source_key": grant.source_key,
            "source_type": grant.source_type,
            "user_ids": sorted(grant.resolved.user_ids) if grant.resolved is not None else [],
            "resolver": grant.resolved.resolver if grant.resolved is not None else None,
            "resolved_at": grant.resolved.resolved_at if grant.resolved is not None else None,
        }
        for grant in grants
    )
    if not fact_payloads:
        return "0"
    canonical = json.dumps(fact_payloads, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
