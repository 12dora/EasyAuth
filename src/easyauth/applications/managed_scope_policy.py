from __future__ import annotations

from dataclasses import dataclass

from .models import (
    MANAGED_SCOPE_POLICY_RESOLVER_DISABLED,
    MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
    MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
    MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
    App,
    AuthorizationGroupGrant,
    ManagedScopePolicy,
)


@dataclass(frozen=True, slots=True)
class EffectiveManagedScopePolicy:
    policy: ManagedScopePolicy
    source: str
    inherited_from: str | None
    resolver: str


class ManagedScopePolicyAppMismatchError(ValueError):
    pass


class ManagedScopePolicyService:
    @staticmethod
    def get_app_default_policy(*, app: App) -> ManagedScopePolicy | None:
        return ManagedScopePolicy.objects.filter(
            app=app,
            target_type=MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
            target_id=app.id,
            scope=MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
        ).first()

    @staticmethod
    def get_grant_override_policy(
        *,
        app: App,
        grant: AuthorizationGroupGrant,
    ) -> ManagedScopePolicy | None:
        if grant.authorization_group.app_id != app.id:
            message = "Grant must belong to the same app."
            raise ManagedScopePolicyAppMismatchError(message)
        return ManagedScopePolicy.objects.filter(
            app=app,
            target_type=MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
            target_id=grant.id,
            scope=MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
        ).first()

    @staticmethod
    def get_effective_policy(
        *,
        app: App,
        grant: AuthorizationGroupGrant | None = None,
    ) -> EffectiveManagedScopePolicy | None:
        if grant is not None:
            override = ManagedScopePolicyService.get_grant_override_policy(app=app, grant=grant)
            if override is not None:
                return _effective_policy(
                    policy=override,
                    source=MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
                    inherited_from=None,
                )
            app_default = ManagedScopePolicyService.get_app_default_policy(app=app)
            if app_default is None:
                return None
            return _effective_policy(
                policy=app_default,
                source=MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
                inherited_from=MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
            )

        app_default = ManagedScopePolicyService.get_app_default_policy(app=app)
        if app_default is None:
            return None
        return _effective_policy(
            policy=app_default,
            source=MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
            inherited_from=None,
        )


def _effective_policy(
    *,
    policy: ManagedScopePolicy,
    source: str,
    inherited_from: str | None,
) -> EffectiveManagedScopePolicy | None:
    if not policy.enabled or policy.resolver == MANAGED_SCOPE_POLICY_RESOLVER_DISABLED:
        return None
    return EffectiveManagedScopePolicy(
        policy=policy,
        source=source,
        inherited_from=inherited_from,
        resolver=policy.resolver,
    )
