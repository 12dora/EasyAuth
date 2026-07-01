from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from django.db import transaction
from django.http import HttpRequest, JsonResponse

from easyauth.admin_console.catalog_relationships import ResolvedGroupReference
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
from easyauth.admin_console.permission_catalog_api import (
    console_permissions as read_permissions,
)
from easyauth.admin_console.permission_catalog_data import permission_item
from easyauth.admin_console.permission_payloads import (
    PermissionCreatePayload,
    PermissionUpdatePayload,
)
from easyauth.admin_console.permission_write_helpers import (
    apply_permission_deprecation,
    apply_permission_update,
    permission_group,
    permission_update_payload,
    resolved_group_reference,
)
from easyauth.applications.catalog_version import bump_catalog_version
from easyauth.applications.models import AppScope, Permission, PermissionGroup

if TYPE_CHECKING:
    from easyauth.applications.models import App
    from easyauth.applications.ownership import ConsoleActor

type PermissionUpdateInputs = tuple["App", "ConsoleActor", Permission]


def console_permissions(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method == "GET":
        return read_permissions(request, app_key)
    if request.method == "POST":
        return _create_permission(request, app_key)
    if request.method == "PATCH":
        return _update_permission(request, app_key)
    return method_not_allowed_response()


def console_permission_detail(
    request: HttpRequest,
    app_key: str,
    permission_key: str,
) -> JsonResponse:
    if request.method != "PATCH":
        return method_not_allowed_response()
    return _update_permission(request, app_key, permission_key)


def _create_permission(request: HttpRequest, app_key: str) -> JsonResponse:
    match write_context(request, app_key):
        case CatalogWriteContext(app=app, actor=actor):
            pass
        case JsonResponse() as response:
            return response
    match parse_payload(request, PermissionCreatePayload, "权限参数无效。"):
        case PermissionCreatePayload() as payload:
            pass
        case JsonResponse() as response:
            return response
    match _new_permission(app_id=app.id, payload=payload):
        case Permission() as permission:
            pass
        case JsonResponse() as response:
            return response
    if response := _validate_permission_supported_scopes(
        app_id=app.id,
        supported_scopes=_supported_scope_keys(permission),
        is_active=permission.is_active,
    ):
        return response
    with transaction.atomic():
        match save_model(permission):
            case None:
                pass
            case JsonResponse() as response:
                return response
        record_catalog_event(
            CatalogEvent(
                app=app,
                actor=actor,
                action="permission_created",
                target_type="permission",
                target_id=str(permission.id),
                metadata={"permission_key": permission.key},
            ),
        )
        _ = bump_catalog_version(
            app,
            actor_id=actor.user_id,
            reason="permission_created",
            metadata={"permission_key": permission.key},
        )
    return json_response({"item": permission_item(permission)}, status=HTTPStatus.CREATED)


def _new_permission(
    *,
    app_id: int,
    payload: PermissionCreatePayload,
) -> Permission | JsonResponse:
    if Permission.objects.filter(app_id=app_id, key=payload.key).exists():
        return conflict_response("权限 key 已存在。")
    match resolved_group_reference(app_id=app_id, payload=payload):
        case ResolvedGroupReference(group_id=group_id):
            pass
        case JsonResponse() as response:
            return response
    match permission_group(group_id=group_id, app_id=app_id):
        case PermissionGroup() as group:
            permission = Permission(
                app_id=app_id,
                group=group,
                key=payload.key,
                name=payload.name,
                description=payload.description,
                is_active=payload.is_active,
                supported_scopes=payload.supported_scopes,
                risk_level=payload.risk_level,
            )
        case None:
            permission = Permission(
                app_id=app_id,
                group=None,
                key=payload.key,
                name=payload.name,
                description=payload.description,
                is_active=payload.is_active,
                supported_scopes=payload.supported_scopes,
                risk_level=payload.risk_level,
            )
        case JsonResponse() as response:
            return response
    apply_permission_deprecation(permission, payload)
    return permission


def _update_permission(
    request: HttpRequest,
    app_key: str,
    permission_key: str | None = None,
) -> JsonResponse:
    match _permission_update_inputs(request, app_key, permission_key):
        case (app, actor, permission):
            pass
        case JsonResponse() as response:
            return response
    return _save_permission_update(app, actor, permission)


def _permission_update_inputs(
    request: HttpRequest,
    app_key: str,
    permission_key: str | None,
) -> PermissionUpdateInputs | JsonResponse:
    match write_context(request, app_key):
        case CatalogWriteContext(app=app, actor=actor):
            pass
        case JsonResponse() as response:
            return response
    match permission_update_payload(request, app_key, permission_key):
        case PermissionUpdatePayload() as payload:
            pass
        case JsonResponse() as response:
            return response
    permission = Permission.objects.filter(app=app, id=payload.id).first()
    if permission is None:
        return semantic_response("权限不属于当前 App。")
    match apply_permission_update(permission, payload):
        case None:
            pass
        case JsonResponse() as response:
            return response
    if response := _validate_permission_supported_scopes(
        app_id=app.id,
        supported_scopes=_supported_scope_keys(permission),
        is_active=permission.is_active,
    ):
        return response
    return app, actor, permission


def _save_permission_update(
    app: App,
    actor: ConsoleActor,
    permission: Permission,
) -> JsonResponse:
    with transaction.atomic():
        match save_model(permission):
            case None:
                pass
            case JsonResponse() as response:
                return response
        record_catalog_event(
            CatalogEvent(
                app=app,
                actor=actor,
                action="permission_updated",
                target_type="permission",
                target_id=str(permission.id),
                metadata={"permission_key": permission.key},
            ),
        )
        _ = bump_catalog_version(
            app,
            actor_id=actor.user_id,
            reason="permission_updated",
            metadata={"permission_key": permission.key},
        )
    return json_response({"item": permission_item(permission)})


def _validate_permission_supported_scopes(
    *,
    app_id: int,
    supported_scopes: list[str],
    is_active: bool,
) -> JsonResponse | None:
    if is_active and not supported_scopes:
        return semantic_response("启用的权限必须显式配置 supported_scopes。")
    if len(set(supported_scopes)) != len(supported_scopes):
        return semantic_response("supported_scopes 不能重复。")
    if not supported_scopes:
        return None
    existing_scope_keys = set(
        AppScope.objects.filter(app_id=app_id, key__in=supported_scopes).values_list(
            "key",
            flat=True,
        ),
    )
    missing_scope_keys = sorted(set(supported_scopes) - existing_scope_keys)
    if missing_scope_keys:
        return semantic_response("supported_scopes 引用了不存在的 Scope。")
    return None


def _supported_scope_keys(permission: Permission) -> list[str]:
    supported_scopes = permission.supported_scopes
    if isinstance(supported_scopes, list) and all(
        isinstance(scope_key, str) for scope_key in supported_scopes
    ):
        return [scope_key for scope_key in supported_scopes if isinstance(scope_key, str)]
    return []
