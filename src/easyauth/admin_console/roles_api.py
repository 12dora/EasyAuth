from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar

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
from easyauth.admin_console.permission_catalog_api import (
    console_roles as read_roles,
)
from easyauth.admin_console.permission_catalog_data import role_item
from easyauth.applications.models import Role


class RoleCreatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    requestable: bool = True
    is_active: bool = True


class RoleUpdatePayload(ResourceIdPayload):
    key: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    requestable: bool | None = None
    is_active: bool | None = None


class RoleKeyUpdatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    key: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    requestable: bool | None = None
    is_active: bool | None = None


def console_roles(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method == "GET":
        return read_roles(request, app_key)
    if request.method == "POST":
        return _create_role(request, app_key)
    if request.method == "PATCH":
        return _update_role(request, app_key)
    return method_not_allowed_response()


def console_role_detail(request: HttpRequest, app_key: str, role_key: str) -> JsonResponse:
    if request.method != "PATCH":
        return method_not_allowed_response()
    return _update_role(request, app_key, role_key)


def _create_role(request: HttpRequest, app_key: str) -> JsonResponse:
    match write_context(request, app_key):
        case CatalogWriteContext(app=app, actor=actor):
            pass
        case JsonResponse() as response:
            return response
    match parse_payload(request, RoleCreatePayload, "角色参数无效。"):
        case RoleCreatePayload() as payload:
            pass
        case JsonResponse() as response:
            return response
    if Role.objects.filter(app=app, key=payload.key).exists():
        return conflict_response("角色 key 已存在。")
    role = Role(
        app=app,
        key=payload.key,
        name=payload.name,
        description=payload.description,
        requestable=payload.requestable,
        is_active=payload.is_active,
    )
    match save_model(role):
        case None:
            pass
        case JsonResponse() as response:
            return response
    record_catalog_event(
        CatalogEvent(
            app=app,
            actor=actor,
            action="role_created",
            target_type="role",
            target_id=str(role.id),
            metadata={"role_key": role.key, "requestable": role.requestable},
        ),
    )
    return json_response({"item": role_item(role)}, status=HTTPStatus.CREATED)


def _update_role(request: HttpRequest, app_key: str, role_key: str | None = None) -> JsonResponse:
    match write_context(request, app_key):
        case CatalogWriteContext(app=app, actor=actor):
            pass
        case JsonResponse() as response:
            return response
    match _role_update_payload(request, app_key, role_key):
        case RoleUpdatePayload() as payload:
            pass
        case JsonResponse() as response:
            return response
    role = Role.objects.filter(app=app, id=payload.id).first()
    if role is None:
        return semantic_response("角色不属于当前 App。")
    match _apply_role_update(role, payload):
        case None:
            pass
        case JsonResponse() as response:
            return response
    match save_model(role):
        case None:
            pass
        case JsonResponse() as response:
            return response
    record_catalog_event(
        CatalogEvent(
            app=app,
            actor=actor,
            action="role_updated",
            target_type="role",
            target_id=str(role.id),
            metadata={"role_key": role.key, "requestable": role.requestable},
        ),
    )
    return json_response({"item": role_item(role)})


def _role_update_payload(
    request: HttpRequest,
    app_key: str,
    role_key: str | None,
) -> RoleUpdatePayload | JsonResponse:
    if role_key is None:
        return parse_payload(request, RoleUpdatePayload, "角色参数无效。")
    match parse_payload(request, RoleKeyUpdatePayload, "角色参数无效。"):
        case RoleKeyUpdatePayload() as payload:
            match _role_id(app_key, role_key):
                case int() as role_id:
                    return RoleUpdatePayload(
                        id=role_id,
                        key=payload.key,
                        name=payload.name,
                        description=payload.description,
                        requestable=payload.requestable,
                        is_active=payload.is_active,
                    )
                case JsonResponse() as response:
                    return response
        case JsonResponse() as response:
            return response


def _role_id(app_key: str, role_key: str) -> int | JsonResponse:
    role = Role.objects.filter(app__app_key=app_key, key=role_key).first()
    if role is None:
        return semantic_response("角色不属于当前 App。")
    return role.id


def _apply_role_update(role: Role, payload: RoleUpdatePayload) -> JsonResponse | None:
    if payload.key is not None and payload.key != role.key:
        if Role.objects.filter(app=role.app, key=payload.key).exists():
            return conflict_response("角色 key 已存在。")
        role.key = payload.key
    if payload.name is not None:
        role.name = payload.name
    if payload.description is not None:
        role.description = payload.description
    if payload.requestable is not None:
        role.requestable = payload.requestable
    if payload.is_active is not None:
        role.is_active = payload.is_active
    return None
