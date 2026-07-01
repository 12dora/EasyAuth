from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field

from easyauth.admin_console.catalog_write_common import (
    CatalogEvent,
    CatalogWriteContext,
    ResourceIdPayload,
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
from easyauth.admin_console.permission_catalog_data import scope_item, scopes_payload
from easyauth.applications.catalog_version import bump_catalog_version
from easyauth.applications.models import App, AppScope

if TYPE_CHECKING:
    from easyauth.applications.ownership import ConsoleActor


class ScopeCreatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    display_order: int = 0
    is_active: bool = True


class ScopeUpdatePayload(ResourceIdPayload):
    key: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    display_order: int | None = None
    is_active: bool | None = None


class ScopeKeyUpdatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    key: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    display_order: int | None = None
    is_active: bool | None = None


def console_scopes(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method == "GET":
        return read_context_response(request, app_key, scopes_payload)
    if request.method == "POST":
        return _create_scope(request, app_key)
    if request.method == "PATCH":
        return _update_scope(request, app_key)
    return method_not_allowed_response()


def console_scope_detail(request: HttpRequest, app_key: str, scope_key: str) -> JsonResponse:
    if request.method != "PATCH":
        return method_not_allowed_response()
    return _update_scope(request, app_key, scope_key)


def _create_scope(request: HttpRequest, app_key: str) -> JsonResponse:
    match write_context(request, app_key):
        case CatalogWriteContext(app=app, actor=actor):
            pass
        case JsonResponse() as response:
            return response
    match parse_payload(request, ScopeCreatePayload, "Scope 参数无效。"):
        case ScopeCreatePayload() as payload:
            pass
        case JsonResponse() as response:
            return response
    if AppScope.objects.filter(app=app, key=payload.key).exists():
        return conflict_response("Scope key 已存在。")
    scope = AppScope(
        app=app,
        key=payload.key,
        name=payload.name,
        description=payload.description,
        display_order=payload.display_order,
        is_active=payload.is_active,
    )
    with transaction.atomic():
        match save_model(scope):
            case None:
                pass
            case JsonResponse() as response:
                return response
        _record_scope_event(app, actor, "scope_created", scope)
        _bump_scope_version(app, actor.user_id, "scope_created", scope)
    return json_response({"item": scope_item(scope)}, status=HTTPStatus.CREATED)


def _update_scope(request: HttpRequest, app_key: str, scope_key: str | None = None) -> JsonResponse:
    match write_context(request, app_key):
        case CatalogWriteContext(app=app, actor=actor):
            pass
        case JsonResponse() as response:
            return response
    match _scope_update_payload(request, app_key, scope_key):
        case ScopeUpdatePayload() as payload:
            pass
        case JsonResponse() as response:
            return response
    scope = AppScope.objects.filter(app=app, id=payload.id).first()
    if scope is None:
        return semantic_response("Scope 不属于当前 App。")
    if response := _apply_scope_update(scope, payload):
        return response
    with transaction.atomic():
        match save_model(scope):
            case None:
                pass
            case JsonResponse() as response:
                return response
        _record_scope_event(app, actor, "scope_updated", scope)
        _bump_scope_version(app, actor.user_id, "scope_updated", scope)
    return json_response({"item": scope_item(scope)})


def _apply_scope_update(
    scope: AppScope,
    payload: ScopeUpdatePayload,
) -> JsonResponse | None:
    if payload.key is not None and payload.key != scope.key:
        return semantic_response("Scope key 不可变。")
    _apply_scope_fields(scope, payload)
    return None


def _apply_scope_fields(scope: AppScope, payload: ScopeUpdatePayload) -> None:
    if payload.name is not None:
        scope.name = payload.name
    if payload.description is not None:
        scope.description = payload.description
    if payload.display_order is not None:
        scope.display_order = payload.display_order
    if payload.is_active is not None:
        scope.is_active = payload.is_active


def _scope_update_payload(
    request: HttpRequest,
    app_key: str,
    scope_key: str | None,
) -> ScopeUpdatePayload | JsonResponse:
    if scope_key is None:
        return parse_payload(request, ScopeUpdatePayload, "Scope 参数无效。")
    match parse_payload(request, ScopeKeyUpdatePayload, "Scope 参数无效。"):
        case ScopeKeyUpdatePayload() as payload:
            scope = AppScope.objects.filter(app__app_key=app_key, key=scope_key).first()
            if scope is None:
                return semantic_response("Scope 不属于当前 App。")
            return ScopeUpdatePayload(
                id=scope.id,
                key=payload.key,
                name=payload.name,
                description=payload.description,
                display_order=payload.display_order,
                is_active=payload.is_active,
            )
        case JsonResponse() as response:
            return response


def _bump_scope_version(app: App, actor_id: str, reason: str, scope: AppScope) -> None:
    _ = bump_catalog_version(
        app,
        actor_id=actor_id,
        reason=reason,
        metadata={"scope_key": scope.key},
    )


def _record_scope_event(
    app: App,
    actor: ConsoleActor,
    action: str,
    scope: AppScope,
) -> None:
    record_catalog_event(
        CatalogEvent(
            app=app,
            actor=actor,
            action=action,
            target_type="scope",
            target_id=str(scope.id),
            metadata={"scope_key": scope.key},
        ),
    )
