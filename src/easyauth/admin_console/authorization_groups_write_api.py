from __future__ import annotations

from http import HTTPStatus

from django.db import transaction
from django.http import HttpRequest, JsonResponse

from easyauth.admin_console.authorization_group_grants import (
    record_group_event,
    replace_grants,
    resolve_grants,
)
from easyauth.admin_console.authorization_groups_payloads import (
    AuthorizationGroupPayload,
    ResolvedAuthorizationGroupGrant,
)
from easyauth.admin_console.catalog_write_common import (
    CatalogWriteContext,
    conflict_response,
    json_response,
    parse_payload,
    save_model,
    semantic_response,
    write_context,
)
from easyauth.admin_console.permission_catalog_data import authorization_group_item
from easyauth.applications.catalog_version import bump_catalog_version
from easyauth.applications.models import App, AuthorizationGroup
from easyauth.applications.ownership import ConsoleActor

type AuthorizationGroupUpdateInputs = tuple[
    App,
    ConsoleActor,
    AuthorizationGroupPayload,
    AuthorizationGroup,
]
type AuthorizationGroupCreateInputs = tuple[
    App,
    ConsoleActor,
    AuthorizationGroupPayload,
    tuple[ResolvedAuthorizationGroupGrant, ...],
]


def create_authorization_group(request: HttpRequest, app_key: str) -> JsonResponse:
    match _authorization_group_create_inputs(request, app_key):
        case (app, actor, payload, grants):
            pass
        case JsonResponse() as response:
            return response
    return _save_authorization_group_create(app, actor, payload, grants)


def update_authorization_group(
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
    match resolve_grants(app, payload.grants):
        case tuple() as grants:
            pass
        case JsonResponse() as response:
            return response
    return _save_authorization_group_update(app, actor, group, grants)


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
    match resolve_grants(app, payload.grants):
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
        match replace_grants(group, grants, actor):
            case None:
                pass
            case JsonResponse() as response:
                return response
        record_group_event(app, actor, "authorization_group_created", group)
        _ = bump_catalog_version(
            app,
            actor_id=actor.user_id,
            reason="authorization_group_created",
            metadata={"authorization_group_key": group.key},
        )
    return json_response({"item": authorization_group_item(group)}, status=HTTPStatus.CREATED)


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
        match replace_grants(group, grants, actor):
            case None:
                pass
            case JsonResponse() as response:
                return response
        record_group_event(app, actor, "authorization_group_updated", group)
        _ = bump_catalog_version(
            app,
            actor_id=actor.user_id,
            reason="authorization_group_updated",
            metadata={"authorization_group_key": group.key},
        )
    return json_response({"item": authorization_group_item(group)})


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
