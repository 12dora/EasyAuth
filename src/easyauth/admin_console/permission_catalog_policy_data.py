from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from easyauth.applications.managed_scope_policy import (
    EffectiveManagedScopePolicy,
    ManagedScopePolicyService,
)
from easyauth.applications.models import (
    MANAGED_SCOPE_POLICY_RESOLVER_DINGTALK_MANAGER_CHAIN,
    MANAGED_SCOPE_POLICY_RESOLVER_DISABLED,
    MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
    MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
    MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
    App,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    ManagedScopePolicy,
)

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue


@dataclass(frozen=True, slots=True)
class ManagedScopePolicyContext:
    app_default: ManagedScopePolicy | None
    overrides_by_grant_id: dict[int, ManagedScopePolicy]


def managed_scope_policy_context(
    app: App,
    groups: tuple[AuthorizationGroup, ...],
) -> ManagedScopePolicyContext:
    grant_ids: list[int] = []
    for group in groups:
        grants = cast(
            "tuple[object, ...]",
            getattr(group, "_prefetched_grants", ()),
        )
        grant_ids.extend(
            grant.id for grant in grants if isinstance(grant, AuthorizationGroupGrant)
        )
    app_default = ManagedScopePolicyService.get_app_default_policy(app=app)
    overrides_by_grant_id: dict[int, ManagedScopePolicy] = {}
    for policy in ManagedScopePolicy.objects.select_related("app").filter(
        app=app,
        target_type=MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
        authorization_group_grant_id__in=grant_ids,
    ):
        grant_id = cast("int | None", getattr(policy, "authorization_group_grant_id", None))
        if grant_id is not None:
            overrides_by_grant_id[grant_id] = policy
    return ManagedScopePolicyContext(
        app_default=app_default,
        overrides_by_grant_id=overrides_by_grant_id,
    )


def grant_managed_scope_policy_item(
    grant: AuthorizationGroupGrant,
    *,
    policy_context: ManagedScopePolicyContext | None = None,
) -> dict[str, JsonValue]:
    override = (
        policy_context.overrides_by_grant_id.get(grant.id)
        if policy_context is not None
        else ManagedScopePolicyService.get_grant_override_policy(
            app=grant.authorization_group.app,
            grant=grant,
        )
    )
    if override is not None:
        return {
            "mode": _managed_scope_policy_mode(override),
            "resolver": override.resolver,
            "enabled": override.enabled,
            "source": MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
            "health_status": _managed_scope_policy_health(override),
            "health_message": _managed_scope_policy_health_message(override),
        }
    app_default = (
        policy_context.app_default
        if policy_context is not None
        else ManagedScopePolicyService.get_app_default_policy(
            app=grant.authorization_group.app,
        )
    )
    if app_default is not None:
        return {
            "mode": "inherit",
            "resolver": "",
            "enabled": False,
            "source": MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
            "health_status": "healthy",
            "health_message": "继承应用默认管理范围策略。",
        }
    return {
        "mode": "inherit",
        "resolver": "",
        "enabled": False,
        "source": "",
        "health_status": "blocked",
        "health_message": "必须配置管理范围计算方式后才能生效。",
    }


def effective_managed_scope_policy_item(
    grant: AuthorizationGroupGrant,
    *,
    policy_context: ManagedScopePolicyContext | None = None,
) -> dict[str, JsonValue] | None:
    if policy_context is None:
        effective = ManagedScopePolicyService.get_effective_policy(
            app=grant.authorization_group.app,
            grant=grant,
        )
    else:
        override = policy_context.overrides_by_grant_id.get(grant.id)
        app_default = policy_context.app_default
        if override is not None:
            if _managed_scope_policy_disabled(override):
                effective = None
            else:
                effective = EffectiveManagedScopePolicy(
                    policy=override,
                    resolver=override.resolver,
                    source=MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
                    inherited_from=None,
                )
        elif app_default is not None:
            if _managed_scope_policy_disabled(app_default):
                effective = None
            else:
                effective = EffectiveManagedScopePolicy(
                    policy=app_default,
                    resolver=app_default.resolver,
                    source=MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
                    inherited_from=MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
                )
        else:
            effective = None
    if effective is None:
        return None
    return {
        "resolver": effective.resolver,
        "enabled": effective.policy.enabled,
        "source": effective.source,
        "inherited_from": effective.inherited_from,
        "health_status": "healthy",
        "health_message": "管理范围策略已配置。",
    }


def _managed_scope_policy_mode(policy: ManagedScopePolicy) -> str:
    if policy.resolver == MANAGED_SCOPE_POLICY_RESOLVER_DISABLED:
        return MANAGED_SCOPE_POLICY_RESOLVER_DISABLED
    if policy.resolver == MANAGED_SCOPE_POLICY_RESOLVER_DINGTALK_MANAGER_CHAIN:
        return "override"
    return policy.resolver


def _managed_scope_policy_health(policy: ManagedScopePolicy) -> str:
    if not policy.enabled or policy.resolver == MANAGED_SCOPE_POLICY_RESOLVER_DISABLED:
        return "disabled"
    if policy.scope != MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS:
        return "invalid"
    return "healthy"


def _managed_scope_policy_health_message(policy: ManagedScopePolicy) -> str:
    if not policy.enabled or policy.resolver == MANAGED_SCOPE_POLICY_RESOLVER_DISABLED:
        return "当前 grant 不启用管理范围授权。"
    if policy.scope != MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS:
        return "管理范围策略 scope 无效。"
    return "管理范围策略已配置。"


def _managed_scope_policy_disabled(policy: ManagedScopePolicy) -> bool:
    return not policy.enabled or policy.resolver == MANAGED_SCOPE_POLICY_RESOLVER_DISABLED
