from __future__ import annotations

from typing import TYPE_CHECKING, Final

from easyauth.applications.managed_scope_policy import ManagedScopePolicyService
from easyauth.applications.models import (
    MANAGED_SCOPE_POLICY_RESOLVER_DINGTALK_MANAGER_CHAIN,
    App,
    AuthorizationGroupGrant,
)
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.query_types import ResolvedManagedUsers
from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryClient,
    AuthentikDirectoryError,
)

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
    if effective_policy.resolver != MANAGED_SCOPE_POLICY_RESOLVER_DINGTALK_MANAGER_CHAIN:
        _record_resolution_failed(
            app=app,
            authorization_group_grant=authorization_group_grant,
            resolver=effective_policy.resolver,
            error_code="managed_scope_resolver_unsupported",
        )
        return None
    if not user.dingtalk_corp_id or not user.dingtalk_userid:
        _record_resolution_failed(
            app=app,
            authorization_group_grant=authorization_group_grant,
            resolver=effective_policy.resolver,
            error_code="managed_scope_user_dingtalk_binding_missing",
        )
        return None

    try:
        managed_users = _managed_users_from_directory(user, directory_cache)
    except AuthentikDirectoryError as error:
        # 基础设施瞬时故障不允许静默丢弃 grant: 版本号不变而内容变小会污染下游快照缓存,
        # EasyTrade 会把这次"缺失"当成真实撤权。必须 fail-fast。
        _record_resolution_failed(
            app=app,
            authorization_group_grant=authorization_group_grant,
            resolver=effective_policy.resolver,
            error_code="managed_scope_directory_unavailable",
        )
        raise ManagedUsersResolutionUnavailableError from error
    if managed_users.stale:
        _record_resolution_failed(
            app=app,
            authorization_group_grant=authorization_group_grant,
            resolver=effective_policy.resolver,
            error_code="managed_scope_directory_stale",
        )
        raise ManagedUsersResolutionUnavailableError

    user_ids = tuple(
        user_id
        for user_id in managed_users.active_authentik_user_ids
        if user_id != user.authentik_user_id
    )
    return ResolvedManagedUsers(
        user_ids=user_ids,
        resolver=effective_policy.resolver,
        resolved_at=managed_users.resolved_at,
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
