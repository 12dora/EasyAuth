"""门户申请目录的审批人解析: 查找候选、解析规则与默认审批人。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from django.db.models import Q

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import (
    App,
    AppMembership,
    ApprovalRule,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from easyauth.api.errors import JsonValue

MANAGED_USERS_SCOPE = "MANAGED_USERS"
APPROVER_RESOLUTION_DEFAULT_POLICY = "default_policy"
APPROVER_RESOLUTION_DIRECT_MANAGER_MISSING = "direct_manager_missing"
APPROVER_RESOLUTION_RESOLVED_BY_DIRECT_MANAGER = "resolved_by_direct_manager"

type _DingTalkBindingKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class ApproverResolution:
    user_ids: tuple[str, ...]
    status: str


@dataclass(frozen=True, slots=True)
class _ApproverLookup:
    authentik_user_ids: set[str]
    direct_manager_key: _DingTalkBindingKey | None


@dataclass(frozen=True, slots=True)
class RequestCatalogApprovers:
    default_approver_by_app_id: dict[int, ApproverResolution]
    default_approver_by_group_id: dict[int, ApproverResolution]
    default_approver_by_permission_id: dict[int, ApproverResolution]
    approver_candidates: tuple[UserMirror, ...]


class _RequestCatalogApproverSource(Protocol):
    @property
    def apps(self) -> tuple[App, ...]: ...

    @property
    def authorization_groups(self) -> tuple[AuthorizationGroup, ...]: ...

    @property
    def permissions(self) -> tuple[Permission, ...]: ...


def resolve_request_catalog_approvers(
    catalog: _RequestCatalogApproverSource,
    user: UserMirror,
) -> RequestCatalogApprovers:
    approver_lookup = _approver_lookup(
        catalog.apps,
        catalog.authorization_groups,
        catalog.permissions,
        user,
    )
    approver_users = _active_approver_users(approver_lookup)
    resolver = _ApproverResolver(approver_users)
    direct_manager_resolution = _direct_manager_approver_resolution(user, resolver)
    default_approver_by_app_id = _app_default_approver_by_app_id(
        catalog.apps,
        user,
        resolver,
    )
    default_approver_by_group_id = _approval_rule_approvers_by_group_id(
        catalog.authorization_groups,
        resolver,
        direct_manager_resolution,
    )
    default_approver_by_permission_id = _approval_rule_approvers_by_permission_id(
        catalog.permissions,
        resolver,
        direct_manager_resolution,
    )
    return RequestCatalogApprovers(
        default_approver_by_app_id=default_approver_by_app_id,
        default_approver_by_group_id=default_approver_by_group_id,
        default_approver_by_permission_id=default_approver_by_permission_id,
        approver_candidates=_approver_candidates(
            approver_users,
            (
                direct_manager_resolution,
                *default_approver_by_app_id.values(),
                *default_approver_by_group_id.values(),
                *default_approver_by_permission_id.values(),
            ),
        ),
    )


def _active_approver_users(lookup: _ApproverLookup) -> tuple[UserMirror, ...]:
    if not lookup.authentik_user_ids and lookup.direct_manager_key is None:
        return ()
    query = Q(authentik_user_id__in=lookup.authentik_user_ids)
    if lookup.direct_manager_key is not None:
        source_slug, corp_id, manager_userid = lookup.direct_manager_key
        query |= Q(
            dingtalk_source_slug=source_slug,
            dingtalk_corp_id=corp_id,
            dingtalk_userid=manager_userid,
        )
    return tuple(
        UserMirror.objects.filter(status=USER_STATUS_ACTIVE)
        .filter(query)
        .order_by("authentik_user_id"),
    )


def _approver_lookup(
    apps: tuple[App, ...],
    groups: tuple[AuthorizationGroup, ...],
    permissions: tuple[Permission, ...],
    user: UserMirror,
) -> _ApproverLookup:
    authentik_user_ids = set(
        cast(
            "Iterable[str]",
            AppMembership.objects.filter(
                app_id__in=(app.id for app in apps),
                role="owner",
                is_active=True,
            ).values_list("user_id", flat=True),
        ),
    )
    rule_approver_rows = ApprovalRule.objects.filter(
        Q(authorization_group_id__in=(group.id for group in groups))
        | Q(permission_id__in=(permission.id for permission in permissions)),
        is_active=True,
    ).values_list("approver_userids", flat=True)
    for raw_user_ids in cast("Iterable[object]", rule_approver_rows):
        if not isinstance(raw_user_ids, list):
            continue
        authentik_user_ids.update(
            raw_user_id
            for raw_user_id in cast("list[object]", raw_user_ids)
            if isinstance(raw_user_id, str)
        )
    authentik_user_ids.discard("")
    return _ApproverLookup(
        authentik_user_ids=authentik_user_ids,
        direct_manager_key=_direct_manager_key(user),
    )


def _direct_manager_key(user: UserMirror) -> _DingTalkBindingKey | None:
    manager_userid = user.manager_userid.strip()
    if not manager_userid:
        return None
    if not user.dingtalk_source_slug or not user.dingtalk_corp_id:
        return None
    return (user.dingtalk_source_slug, user.dingtalk_corp_id, manager_userid)


def _approver_candidates(
    approver_users: tuple[UserMirror, ...],
    resolutions: tuple[ApproverResolution, ...],
) -> tuple[UserMirror, ...]:
    # 只暴露与本次申请相关的候选审批人(直属主管/规则审批人/App owner),
    # 不把全公司在职目录发给任意登录员工。
    candidate_user_ids: set[str] = set()
    for resolution in resolutions:
        candidate_user_ids.update(resolution.user_ids)
    return tuple(user for user in approver_users if user.authentik_user_id in candidate_user_ids)


def approver_option(user: UserMirror) -> dict[str, JsonValue]:
    # 只返回展示所需的最小字段, 不泄漏邮箱和部门。
    return {
        "user_id": user.authentik_user_id,
        "name": user.name,
    }


def _app_default_approver_by_app_id(
    apps: tuple[App, ...],
    user: UserMirror,
    resolver: _ApproverResolver,
) -> dict[int, ApproverResolution]:
    app_ids = tuple(app.id for app in apps)
    owner_user_ids_by_app_id = _owner_user_ids_by_app_id(app_ids)
    manager_user_ids = resolver.resolve_direct_manager(user)
    return {
        app.id: ApproverResolution(
            user_ids=manager_user_ids or resolver.resolve(owner_user_ids_by_app_id.get(app.id, ())),
            status=APPROVER_RESOLUTION_DEFAULT_POLICY,
        )
        for app in apps
    }


def _direct_manager_approver_resolution(
    user: UserMirror,
    resolver: _ApproverResolver,
) -> ApproverResolution:
    manager_user_ids = resolver.resolve_direct_manager(user)
    if manager_user_ids:
        return ApproverResolution(
            user_ids=manager_user_ids,
            status=APPROVER_RESOLUTION_RESOLVED_BY_DIRECT_MANAGER,
        )
    return ApproverResolution(
        user_ids=(),
        status=APPROVER_RESOLUTION_DIRECT_MANAGER_MISSING,
    )


def _owner_user_ids_by_app_id(app_ids: tuple[int, ...]) -> dict[int, tuple[str, ...]]:
    owner_user_ids_by_app_id: dict[int, list[str]] = {app_id: [] for app_id in app_ids}
    membership_rows = (
        AppMembership.objects.filter(
            app_id__in=app_ids,
            role="owner",
            is_active=True,
        )
        .order_by("app_id", "user_id")
        .values_list("app_id", "user_id")
    )
    for raw_app_id, raw_user_id in cast("Iterable[tuple[object, object]]", membership_rows):
        app_id = cast("int", raw_app_id)
        user_id = cast("str", raw_user_id)
        owner_user_ids_by_app_id.setdefault(app_id, []).append(user_id)
    return {
        app_id: tuple(owner_user_ids) for app_id, owner_user_ids in owner_user_ids_by_app_id.items()
    }


def _approval_rule_approvers_by_group_id(
    groups: tuple[AuthorizationGroup, ...],
    resolver: _ApproverResolver,
    direct_manager_resolution: ApproverResolution,
) -> dict[int, ApproverResolution]:
    group_ids = tuple(group.id for group in groups)
    if not group_ids:
        return {}
    defaults: dict[int, ApproverResolution] = {}
    raw_managed_group_ids = AuthorizationGroupGrant.objects.filter(
        authorization_group_id__in=group_ids,
        is_active=True,
        scope_key=MANAGED_USERS_SCOPE,
    ).values_list("authorization_group_id", flat=True)
    managed_group_ids = tuple(
        cast("int", group_id) for group_id in cast("Iterable[object]", raw_managed_group_ids)
    )
    for group_id in managed_group_ids:
        defaults[group_id] = direct_manager_resolution
    rule_rows = (
        ApprovalRule.objects.filter(
            authorization_group_id__in=group_ids,
            is_active=True,
        )
        .order_by("authorization_group_id", "id")
        .values_list(
            "authorization_group_id",
            "approver_userids",
        )
    )
    for raw_group_id, approver_userids in cast("Iterable[tuple[object, object]]", rule_rows):
        group_id = cast("int", raw_group_id)
        if group_id in defaults:
            continue
        approver_user_ids = resolver.resolve(approver_userids)
        if approver_user_ids:
            defaults[group_id] = ApproverResolution(
                user_ids=approver_user_ids,
                status=APPROVER_RESOLUTION_DEFAULT_POLICY,
            )
    return defaults


def _approval_rule_approvers_by_permission_id(
    permissions: tuple[Permission, ...],
    resolver: _ApproverResolver,
    direct_manager_resolution: ApproverResolution,
) -> dict[int, ApproverResolution]:
    permission_ids = tuple(permission.id for permission in permissions)
    if not permission_ids:
        return {}
    defaults: dict[int, ApproverResolution] = {
        permission.id: direct_manager_resolution
        for permission in permissions
        if _permission_targets_managed_users(permission)
    }
    rule_rows = (
        ApprovalRule.objects.filter(
            permission_id__in=permission_ids,
            is_active=True,
        )
        .order_by("permission_id", "id")
        .values_list("permission_id", "approver_userids")
    )
    for raw_permission_id, approver_userids in cast(
        "Iterable[tuple[object, object]]",
        rule_rows,
    ):
        permission_id = cast("int", raw_permission_id)
        if permission_id in defaults:
            continue
        approver_user_ids = resolver.resolve(approver_userids)
        if approver_user_ids:
            defaults[permission_id] = ApproverResolution(
                user_ids=approver_user_ids,
                status=APPROVER_RESOLUTION_DEFAULT_POLICY,
            )
    return defaults


def _permission_targets_managed_users(permission: Permission) -> bool:
    # 与目录侧 `_permission_supports_scope` 同口径, 避免 approvers ↔ data 循环导入。
    supported_scopes = permission.supported_scopes
    return isinstance(supported_scopes, list) and MANAGED_USERS_SCOPE in supported_scopes


class _ApproverResolver:
    def __init__(self, users: tuple[UserMirror, ...]) -> None:
        self._user_id_by_authentik_user_id: dict[str, str] = {
            user.authentik_user_id: user.authentik_user_id for user in users
        }
        self._user_id_by_dingtalk_key: dict[_DingTalkBindingKey, str] = {
            (user.dingtalk_source_slug, user.dingtalk_corp_id, user.dingtalk_userid): (
                user.authentik_user_id
            )
            for user in users
            if user.dingtalk_source_slug and user.dingtalk_corp_id and user.dingtalk_userid
        }

    def resolve(self, raw_user_ids: object) -> tuple[str, ...]:
        if not isinstance(raw_user_ids, (list, tuple)):
            return ()
        resolved_user_ids: list[str] = []
        seen: set[str] = set()
        for raw_user_id in cast("list[object] | tuple[object, ...]", raw_user_ids):
            if not isinstance(raw_user_id, str):
                continue
            user_id = self._user_id_by_authentik_user_id.get(raw_user_id)
            if user_id is None or user_id in seen:
                continue
            seen.add(user_id)
            resolved_user_ids.append(user_id)
        return tuple(resolved_user_ids)

    def resolve_direct_manager(self, user: UserMirror) -> tuple[str, ...]:
        key = _direct_manager_key(user)
        if key is None:
            return ()
        user_id = self._user_id_by_dingtalk_key.get(key)
        return () if user_id is None else (user_id,)


def _json_strings(values: tuple[str, ...]) -> list[JsonValue]:
    result: list[JsonValue] = []
    result.extend(values)
    return result


# 跨模块公开名, 避免 data 导入私有 `_json_strings` 触发 reportPrivateUsage。
json_strings = _json_strings
