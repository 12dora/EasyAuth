from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field

from easyauth.admin_console.catalog_write_common import (
    CatalogEvent,
    CatalogWriteContext,
    conflict_response,
    json_response,
    method_not_allowed_response,
    parse_payload,
    record_catalog_event,
    save_model,
    semantic_response,
    write_context,
)
from easyauth.admin_console.permission_catalog_api import read_context_response
from easyauth.admin_console.permission_catalog_data import (
    authorization_group_item,
    authorization_groups_payload,
)
from easyauth.applications.catalog_version import bump_catalog_version
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

type AuthorizationGroupUpdateInputs = tuple[
    App,
    "ConsoleActor",
    AuthorizationGroupPayload,
    AuthorizationGroup,
]
type AuthorizationGroupCreateInputs = tuple[
    App,
    "ConsoleActor",
    AuthorizationGroupPayload,
    tuple["ResolvedAuthorizationGroupGrant", ...],
]


@dataclass(frozen=True, slots=True)
class ResolvedAuthorizationGroupGrant:
    permission: Permission
    scope_key: str
    is_active: bool
    managed_scope_policy: ManagedScopePolicyPayload | None


class ManagedScopePolicyPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    mode: str = Field(default="inherit", min_length=1, max_length=64)
    resolver: str = Field(default="", max_length=64)
    enabled: bool = True


class AuthorizationGroupGrantPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    permission: str = Field(min_length=1, max_length=128)
    scope: str = Field(min_length=1, max_length=64)
    is_active: bool = True
    managed_scope_policy: ManagedScopePolicyPayload | None = None


class AuthorizationGroupPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    key: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    name_en: str = Field(default="", max_length=128)
    description: str = ""
    description_en: str = ""
    requestable: bool = True
    is_active: bool = True
    grants: tuple[AuthorizationGroupGrantPayload, ...] = ()


def console_authorization_groups(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method == "GET":
        return read_context_response(request, app_key, authorization_groups_payload)
    if request.method == "POST":
        return _create_authorization_group(request, app_key)
    return method_not_allowed_response()


def console_authorization_group_detail(
    request: HttpRequest,
    app_key: str,
    authorization_group_key: str,
) -> JsonResponse:
    if request.method != "PATCH":
        return method_not_allowed_response()
    return _update_authorization_group(request, app_key, authorization_group_key)


def _create_authorization_group(request: HttpRequest, app_key: str) -> JsonResponse:
    match _authorization_group_create_inputs(request, app_key):
        case (app, actor, payload, grants):
            pass
        case JsonResponse() as response:
            return response
    return _save_authorization_group_create(app, actor, payload, grants)


def _authorization_group_create_inputs(
    request: HttpRequest,
    app_key: str,
) -> AuthorizationGroupCreateInputs | JsonResponse:
    match write_context(request, app_key):
        case CatalogWriteContext(app=app, actor=actor):
            pass
        case JsonResponse() as response:
            return response
    match parse_payload(request, AuthorizationGroupPayload, "授权组参数无效。"):
        case AuthorizationGroupPayload() as payload:
            pass
        case JsonResponse() as response:
            return response
    if AuthorizationGroup.objects.filter(app=app, key=payload.key).exists():
        return conflict_response("授权组 key 已存在。")
    match _resolve_grants(app, payload.grants):
        case tuple() as grants:
            pass
        case JsonResponse() as response:
            return response
    return app, actor, payload, grants


def _save_authorization_group_create(
    app: App,
    actor: ConsoleActor,
    payload: AuthorizationGroupPayload,
    grants: tuple[ResolvedAuthorizationGroupGrant, ...],
) -> JsonResponse:
    with transaction.atomic():
        group = AuthorizationGroup(
            app=app,
            key=payload.key,
            kind=payload.kind,
            name=payload.name,
            name_en=payload.name_en,
            description=payload.description,
            description_en=payload.description_en,
            requestable=payload.requestable,
            is_active=payload.is_active,
        )
        match save_model(group):
            case None:
                pass
            case JsonResponse() as response:
                return response
        match _replace_grants(group, grants, actor):
            case None:
                pass
            case JsonResponse() as response:
                return response
        _record_group_event(app, actor, "authorization_group_created", group)
        _ = bump_catalog_version(
            app,
            actor_id=actor.user_id,
            reason="authorization_group_created",
            metadata={"authorization_group_key": group.key},
        )
    return json_response({"item": authorization_group_item(group)}, status=HTTPStatus.CREATED)


def _update_authorization_group(
    request: HttpRequest,
    app_key: str,
    authorization_group_key: str,
) -> JsonResponse:
    match _authorization_group_update_inputs(request, app_key, authorization_group_key):
        case (
            App() as app,
            actor,
            AuthorizationGroupPayload() as payload,
            AuthorizationGroup() as group,
        ):
            pass
        case JsonResponse() as response:
            return response
    if response := _apply_authorization_group_update(app, group, payload):
        return response
    match _resolve_grants(app, payload.grants):
        case tuple() as grants:
            pass
        case JsonResponse() as response:
            return response
    return _save_authorization_group_update(app, actor, group, grants)


def _authorization_group_update_inputs(
    request: HttpRequest,
    app_key: str,
    authorization_group_key: str,
) -> AuthorizationGroupUpdateInputs | JsonResponse:
    match write_context(request, app_key):
        case CatalogWriteContext(app=app, actor=actor):
            pass
        case JsonResponse() as response:
            return response
    match parse_payload(request, AuthorizationGroupPayload, "授权组参数无效。"):
        case AuthorizationGroupPayload() as payload:
            pass
        case JsonResponse() as response:
            return response
    group = AuthorizationGroup.objects.filter(app=app, key=authorization_group_key).first()
    if group is None:
        return semantic_response("授权组不属于当前 App。")
    return app, actor, payload, group


def _save_authorization_group_update(
    app: App,
    actor: ConsoleActor,
    group: AuthorizationGroup,
    grants: tuple[ResolvedAuthorizationGroupGrant, ...],
) -> JsonResponse:
    with transaction.atomic():
        match save_model(group):
            case None:
                pass
            case JsonResponse() as response:
                return response
        match _replace_grants(group, grants, actor):
            case None:
                pass
            case JsonResponse() as response:
                return response
        _record_group_event(app, actor, "authorization_group_updated", group)
        _ = bump_catalog_version(
            app,
            actor_id=actor.user_id,
            reason="authorization_group_updated",
            metadata={"authorization_group_key": group.key},
        )
    return json_response({"item": authorization_group_item(group)})


def _resolve_grants(
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


def _supported_scope_keys(permission: Permission) -> list[str]:
    supported_scopes = permission.supported_scopes
    if isinstance(supported_scopes, list) and all(
        isinstance(scope_key, str) for scope_key in supported_scopes
    ):
        return [scope_key for scope_key in supported_scopes if isinstance(scope_key, str)]
    return []


def _replace_grants(
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


def _apply_authorization_group_update(
    app: App,
    group: AuthorizationGroup,
    payload: AuthorizationGroupPayload,
) -> JsonResponse | None:
    key_conflicts = AuthorizationGroup.objects.filter(app=app, key=payload.key).exists()
    if payload.key != group.key and key_conflicts:
        return conflict_response("授权组 key 已存在。")
    group.key = payload.key
    group.kind = payload.kind
    group.name = payload.name
    group.name_en = payload.name_en
    group.description = payload.description
    group.description_en = payload.description_en
    group.requestable = payload.requestable
    group.is_active = payload.is_active
    return None


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
        target_id=grant.id,
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
        target_id=grant.id,
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


def _record_group_event(
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
