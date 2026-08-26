from __future__ import annotations

from typing import TYPE_CHECKING

from django.http import JsonResponse

from easyauth.admin_console.authorization_groups_payloads import (
    AuthorizationGroupGrantPayload,
    ManagedScopePolicyPayload,
    ResolvedAuthorizationGroupGrant,
)
from easyauth.admin_console.catalog_write_common import (
    CatalogEvent,
    record_catalog_event,
    save_model,
    semantic_response,
)
from easyauth.applications.models import (
    MANAGED_SCOPE_POLICY_ACTIVE_RESOLVERS,
    MANAGED_SCOPE_POLICY_RESOLVER_DISABLED,
    MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
    MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    ManagedScopePolicy,
    Permission,
)

if TYPE_CHECKING:
    from easyauth.applications.ownership import ConsoleActor


def resolve_grants(
    app: App,
    grants: tuple[AuthorizationGroupGrantPayload, ...],
) -> tuple[ResolvedAuthorizationGroupGrant, ...] | JsonResponse:
    resolved: list[ResolvedAuthorizationGroupGrant] = []
    seen: set[tuple[str, str]] = set()
    for payload in grants:
        if response := _validate_unique_grant(payload, seen):
            return response
        match _grant_permission(app, payload):
            case Permission() as permission:
                pass
            case JsonResponse() as response:
                return response
        if payload.scope not in _supported_scope_keys(permission):
            return semantic_response("授权组 grant 的 Scope 不在 Permission supported_scopes 中。")
        if response := _validate_managed_scope_policy_payload(payload.managed_scope_policy):
            return response
        resolved.append(
            ResolvedAuthorizationGroupGrant(
                permission=permission,
                scope_key=payload.scope,
                is_active=payload.is_active,
                managed_scope_policy=payload.managed_scope_policy,
            ),
        )
    return tuple(resolved)


def replace_grants(
    group: AuthorizationGroup,
    grants: tuple[ResolvedAuthorizationGroupGrant, ...],
    actor: ConsoleActor,
) -> JsonResponse | None:
    for payload in grants:
        match _upsert_grant(group, payload):
            case AuthorizationGroupGrant() as grant:
                if response := _replace_grant_managed_scope_policy(group, grant, payload, actor):
                    return response
            case JsonResponse() as response:
                return response
    seen = {(grant.permission.key, grant.scope_key) for grant in grants}
    return _deactivate_missing_grants(group, seen)


def record_group_event(
    app: App,
    actor: ConsoleActor,
    action: str,
    group: AuthorizationGroup,
) -> None:
    record_catalog_event(
        CatalogEvent(
            app=app,
            actor=actor,
            action=action,
            target_type="authorization_group",
            target_id=str(group.id),
            metadata={"authorization_group_key": group.key},
        ),
    )


def _supported_scope_keys(permission: Permission) -> list[str]:
    supported_scopes = permission.supported_scopes
    if isinstance(supported_scopes, list) and all(
        isinstance(scope_key, str) for scope_key in supported_scopes
    ):
        return [scope_key for scope_key in supported_scopes if isinstance(scope_key, str)]
    return []


def _validate_unique_grant(
    payload: AuthorizationGroupGrantPayload,
    seen: set[tuple[str, str]],
) -> JsonResponse | None:
    key = (payload.permission, payload.scope)
    if key in seen:
        return semantic_response("授权组 grant 不能重复。")
    seen.add(key)
    return None


def _upsert_grant(
    group: AuthorizationGroup,
    payload: ResolvedAuthorizationGroupGrant,
) -> AuthorizationGroupGrant | JsonResponse:
    grant, _created = AuthorizationGroupGrant.objects.get_or_create(
        authorization_group=group,
        permission=payload.permission,
        scope_key=payload.scope_key,
        defaults={"is_active": payload.is_active},
    )
    grant.is_active = payload.is_active
    if response := save_model(grant):
        return response
    return grant


def _replace_grant_managed_scope_policy(
    group: AuthorizationGroup,
    grant: AuthorizationGroupGrant,
    payload: ResolvedAuthorizationGroupGrant,
    actor: ConsoleActor,
) -> JsonResponse | None:
    if not payload.is_active:
        if _delete_grant_managed_scope_policy(group, grant):
            _record_managed_scope_policy_updated(
                group,
                actor,
                grant,
                resolver=MANAGED_SCOPE_POLICY_RESOLVER_DISABLED,
            )
        return None
    normalized = _normalized_managed_scope_policy_payload(payload.managed_scope_policy)
    if normalized is None:
        if _delete_grant_managed_scope_policy(group, grant):
            _record_managed_scope_policy_updated(group, actor, grant, resolver="app_default")
        return None
    policy, _created = ManagedScopePolicy.objects.get_or_create(
        app=group.app,
        target_type=MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
        authorization_group_grant=grant,
        scope=MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
        defaults={
            "resolver": normalized.resolver,
            "enabled": normalized.enabled,
        },
    )
    previous = None if _created else (policy.resolver, policy.enabled)
    policy.resolver = normalized.resolver
    policy.enabled = normalized.enabled
    if response := save_model(policy):
        return response
    if previous != (policy.resolver, policy.enabled):
        _record_managed_scope_policy_updated(group, actor, grant, resolver=policy.resolver)
    return None


def _delete_grant_managed_scope_policy(
    group: AuthorizationGroup,
    grant: AuthorizationGroupGrant,
) -> bool:
    deleted_count, _deleted_by_model = ManagedScopePolicy.objects.filter(
        app=group.app,
        target_type=MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
        authorization_group_grant=grant,
        scope=MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
    ).delete()
    return deleted_count > 0


def _grant_permission(
    app: App,
    payload: AuthorizationGroupGrantPayload,
) -> Permission | JsonResponse:
    permission = Permission.objects.filter(app=app, key=payload.permission).first()
    if permission is None:
        return semantic_response("授权组 grant 引用了不存在的 Permission。")
    if not AppScope.objects.filter(app=app, key=payload.scope).exists():
        return semantic_response("授权组 grant 引用了不存在的 Scope。")
    return permission


def _deactivate_missing_grants(
    group: AuthorizationGroup,
    seen: set[tuple[str, str]],
) -> JsonResponse | None:
    existing_grants = AuthorizationGroupGrant.objects.filter(
        authorization_group=group,
    ).select_related("permission")
    for grant in existing_grants:
        key = (grant.permission.key, grant.scope_key)
        if key not in seen and grant.is_active:
            grant.is_active = False
            match save_model(grant):
                case None:
                    _ = _delete_grant_managed_scope_policy(group, grant)
                case JsonResponse() as response:
                    return response
        elif key not in seen:
            _ = _delete_grant_managed_scope_policy(group, grant)
    return None


def _validate_managed_scope_policy_payload(
    payload: ManagedScopePolicyPayload | None,
) -> JsonResponse | None:
    try:
        _ = _normalized_managed_scope_policy_payload(payload)
    except ValueError as error:
        return semantic_response(str(error))
    return None


def _normalized_managed_scope_policy_payload(
    payload: ManagedScopePolicyPayload | None,
) -> ManagedScopePolicyPayload | None:
    if payload is None or payload.mode in {"inherit", "app_default"}:
        return None
    if payload.mode == MANAGED_SCOPE_POLICY_RESOLVER_DISABLED:
        return ManagedScopePolicyPayload(
            mode=MANAGED_SCOPE_POLICY_RESOLVER_DISABLED,
            resolver=MANAGED_SCOPE_POLICY_RESOLVER_DISABLED,
            enabled=True,
        )
    resolver = payload.resolver if payload.mode == "override" else payload.mode
    if resolver == MANAGED_SCOPE_POLICY_RESOLVER_DISABLED:
        return ManagedScopePolicyPayload(
            mode=MANAGED_SCOPE_POLICY_RESOLVER_DISABLED,
            resolver=resolver,
            enabled=payload.enabled,
        )
    if resolver not in MANAGED_SCOPE_POLICY_ACTIVE_RESOLVERS:
        message = "授权组 grant managed_scope_policy resolver 不受支持。"
        raise ValueError(message)
    return ManagedScopePolicyPayload(mode="override", resolver=resolver, enabled=payload.enabled)


def _record_managed_scope_policy_updated(
    group: AuthorizationGroup,
    actor: ConsoleActor,
    grant: AuthorizationGroupGrant,
    *,
    resolver: str,
) -> None:
    record_catalog_event(
        CatalogEvent(
            app=group.app,
            actor=actor,
            action="managed_scope_policy_updated",
            target_type="authorization_group_grant",
            target_id=str(grant.id),
            metadata={
                "authorization_group_key": group.key,
                "permission_key": grant.permission.key,
                "scope": MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
                "resolver": resolver,
            },
        ),
    )
