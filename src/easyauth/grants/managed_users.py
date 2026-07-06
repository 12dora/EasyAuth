from __future__ import annotations

from typing import TYPE_CHECKING, Final

from django.utils import timezone

from easyauth.applications.managed_scope_policy import ManagedScopePolicyService
from easyauth.applications.models import (
    MANAGED_SCOPE_POLICY_ACTIVE_RESOLVERS,
    MANAGED_SCOPE_POLICY_RESOLVER_DINGTALK_MANAGER_CHAIN,
    MANAGED_SCOPE_POLICY_RESOLVER_EASYAUTH_TEAM,
    MANAGED_SCOPE_POLICY_RESOLVER_UNION,
    App,
    AuthorizationGroupGrant,
)
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.query_types import ResolvedManagedUsers
from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryClient,
    AuthentikDirectoryError,
)
from easyauth.teams.services import team_managed_user_ids

MANAGED_USERS_SCOPE = "MANAGED_USERS"
MANAGED_USERS_RESOLVER_ACTOR_ID = "managed_users_resolver"
MANAGED_USERS_DIRECTORY_UNAVAILABLE_MESSAGE: Final = (
    "MANAGED_USERS 解析依赖的组织目录暂不可用。"
)

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror
    from easyauth.audit.models import JsonValue
    from easyauth.integrations.authentik.directory_payloads import DingTalkManagedUsers

# 同一次权限查询内按 (corp_id, manager_userid) 复用目录结果, 避免 K 个 grant 触发 K 次 HTTP。
type ManagedUsersDirectoryCache = dict[tuple[str, str], DingTalkManagedUsers]


class ManagedUsersResolutionUnavailableError(RuntimeError):
    # 组织目录瞬时故障; 必须让本次查询失败, 不得降级成"权限被撤"的成功响应。

    def __init__(self) -> None:
        super().__init__(MANAGED_USERS_DIRECTORY_UNAVAILABLE_MESSAGE)


def resolve_managed_users(
    *,
    user: UserMirror,
    app: App,
    authorization_group_grant: AuthorizationGroupGrant | None = None,
    directory_cache: ManagedUsersDirectoryCache | None = None,
) -> ResolvedManagedUsers | None:
    effective_policy = ManagedScopePolicyService.get_effective_policy(
        app=app,
        grant=authorization_group_grant,
    )
    if effective_policy is None:
        _record_resolution_failed(
            app=app,
            authorization_group_grant=authorization_group_grant,
            resolver="missing",
            error_code="managed_scope_policy_missing",
        )
        return None
    resolver = effective_policy.resolver
    if resolver not in MANAGED_SCOPE_POLICY_ACTIVE_RESOLVERS:
        _record_resolution_failed(
            app=app,
            authorization_group_grant=authorization_group_grant,
            resolver=resolver,
            error_code="managed_scope_resolver_unsupported",
        )
        return None

    if resolver == MANAGED_SCOPE_POLICY_RESOLVER_EASYAUTH_TEAM:
        return team_resolved_managed_users(user, resolver=resolver)

    # dingtalk_manager_chain / union 都需要钉钉主管链。
    team_resolution = (
        team_resolved_managed_users(user, resolver=resolver)
        if resolver == MANAGED_SCOPE_POLICY_RESOLVER_UNION
        else None
    )
    if not user.dingtalk_corp_id or not user.dingtalk_userid:
        _record_resolution_failed(
            app=app,
            authorization_group_grant=authorization_group_grant,
            resolver=resolver,
            error_code="managed_scope_user_dingtalk_binding_missing",
        )
        # 绑定缺失是稳定事实(非瞬时故障): union 下团队侧照常返回,
        # dingtalk_manager_chain 下与既有语义一致地丢弃该 grant 的解析。
        return team_resolution

    try:
        managed_users = _managed_users_from_directory(user, directory_cache)
    except AuthentikDirectoryError as error:
        # 基础设施瞬时故障不允许静默丢弃 grant: 版本号不变而内容变小会污染下游快照缓存,
        # EasyTrade 会把这次"缺失"当成真实撤权。必须 fail-fast, union 亦然。
        _record_resolution_failed(
            app=app,
            authorization_group_grant=authorization_group_grant,
            resolver=resolver,
            error_code="managed_scope_directory_unavailable",
        )
        raise ManagedUsersResolutionUnavailableError from error
    if managed_users.stale:
        _record_resolution_failed(
            app=app,
            authorization_group_grant=authorization_group_grant,
            resolver=resolver,
            error_code="managed_scope_directory_stale",
        )
        raise ManagedUsersResolutionUnavailableError

    chain_user_ids = tuple(
        user_id
        for user_id in managed_users.active_authentik_user_ids
        if user_id != user.authentik_user_id
    )
    if resolver == MANAGED_SCOPE_POLICY_RESOLVER_DINGTALK_MANAGER_CHAIN:
        return ResolvedManagedUsers(
            user_ids=chain_user_ids,
            resolver=resolver,
            resolved_at=managed_users.resolved_at,
        )
    # union: 钉钉链与团队并集; resolved_at 取目录侧时间(两者中较保守的新鲜度口径)。
    team_user_ids = team_resolution.user_ids if team_resolution is not None else ()
    return ResolvedManagedUsers(
        user_ids=tuple(sorted(set(chain_user_ids) | set(team_user_ids))),
        resolver=resolver,
        resolved_at=managed_users.resolved_at,
    )


def team_resolved_managed_users(
    user: UserMirror,
    *,
    resolver: str = MANAGED_SCOPE_POLICY_RESOLVER_EASYAUTH_TEAM,
) -> ResolvedManagedUsers:
    # 本地表查询, 不依赖目录新鲜度, 没有 stale/不可用失败模式。
    return ResolvedManagedUsers(
        user_ids=team_managed_user_ids(user),
        resolver=resolver,
        resolved_at=timezone.now().isoformat(),
    )


def _managed_users_from_directory(
    user: UserMirror,
    directory_cache: ManagedUsersDirectoryCache | None,
) -> DingTalkManagedUsers:
    cache_key = (user.dingtalk_corp_id, user.dingtalk_userid)
    if directory_cache is not None and cache_key in directory_cache:
        return directory_cache[cache_key]
    managed_users = AuthentikDirectoryClient.from_settings().get_managed_users(
        user.dingtalk_corp_id,
        user.dingtalk_userid,
    )
    if directory_cache is not None:
        directory_cache[cache_key] = managed_users
    return managed_users


def _record_resolution_failed(
    *,
    app: App,
    authorization_group_grant: AuthorizationGroupGrant | None,
    resolver: str,
    error_code: str,
) -> None:
    metadata = _resolution_metadata(
        app=app,
        authorization_group_grant=authorization_group_grant,
        resolver=resolver,
    )
    metadata["error_code"] = error_code
    _ = AuditService.record(
        AuditRecord(
            actor_type="system",
            actor_id=MANAGED_USERS_RESOLVER_ACTOR_ID,
            action="managed_users_resolution_failed",
            target_type=_resolution_target_type(authorization_group_grant),
            target_id=_resolution_target_id(app, authorization_group_grant),
            metadata=metadata,
        ),
    )


def _resolution_metadata(
    *,
    app: App,
    authorization_group_grant: AuthorizationGroupGrant | None,
    resolver: str,
) -> dict[str, JsonValue]:
    metadata: dict[str, JsonValue] = {
        "app_key": app.app_key,
        "scope": MANAGED_USERS_SCOPE,
        "resolver": resolver,
    }
    if authorization_group_grant is not None:
        metadata["authorization_group_key"] = authorization_group_grant.authorization_group.key
        metadata["permission_key"] = authorization_group_grant.permission.key
    return metadata


def _resolution_target_type(
    authorization_group_grant: AuthorizationGroupGrant | None,
) -> str:
    if authorization_group_grant is None:
        return "app"
    return "authorization_group_grant"


def _resolution_target_id(
    app: App,
    authorization_group_grant: AuthorizationGroupGrant | None,
) -> str:
    if authorization_group_grant is None:
        return str(app.id)
    return str(authorization_group_grant.id)
