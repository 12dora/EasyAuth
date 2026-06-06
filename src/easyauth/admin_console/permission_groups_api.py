from __future__ import annotations

from http import HTTPStatus

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
    console_permission_groups as read_permission_groups,
)
from easyauth.admin_console.permission_catalog_data import group_item
from easyauth.admin_console.permission_group_payloads import (
    PermissionGroupCreatePayload,
    PermissionGroupUpdatePayload,
)
from easyauth.admin_console.permission_group_write_helpers import (
    group_update_payload,
    mutate_permission_group,
    parent_group,
    resolved_parent_reference,
)
from easyauth.applications.models import PermissionGroup


def console_permission_groups(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method == "GET":
        return read_permission_groups(request, app_key)
    if request.method == "POST":
        return _create_permission_group(request, app_key)
    if request.method == "PATCH":
        return _update_permission_group(request, app_key)
    return method_not_allowed_response()


def console_permission_group_detail(
    request: HttpRequest,
    app_key: str,
    group_key: str,
) -> JsonResponse:
    if request.method != "PATCH":
        return method_not_allowed_response()
    return _update_permission_group(request, app_key, group_key)


def _create_permission_group(request: HttpRequest, app_key: str) -> JsonResponse:
    match write_context(request, app_key):
        case CatalogWriteContext(app=app, actor=actor):
            pass
        case JsonResponse() as response:
            return response
    match parse_payload(request, PermissionGroupCreatePayload, "权限分组参数无效。"):
        case PermissionGroupCreatePayload() as payload:
            pass
        case JsonResponse() as response:
            return response
    match _new_permission_group(app_id=app.id, payload=payload):
        case PermissionGroup() as group:
            pass
        case JsonResponse() as response:
            return response
    match save_model(group):
        case None:
            pass
        case JsonResponse() as response:
            return response
    record_catalog_event(
        CatalogEvent(
            app=app,
            actor=actor,
            action="permission_group_created",
            target_type="permission_group",
            target_id=str(group.id),
            metadata={"permission_group_key": group.key},
        ),
    )
    return json_response({"item": group_item(group)}, status=HTTPStatus.CREATED)


def _new_permission_group(
    *,
    app_id: int,
    payload: PermissionGroupCreatePayload,
) -> PermissionGroup | JsonResponse:
    if PermissionGroup.objects.filter(app_id=app_id, key=payload.key).exists():
        return conflict_response("权限分组 key 已存在。")
    match resolved_parent_reference(app_id=app_id, payload=payload):
        case ResolvedGroupReference(group_id=parent_id):
            pass
        case JsonResponse() as response:
            return response
    match parent_group(parent_id=parent_id, app_id=app_id):
        case PermissionGroup() as parent:
            return PermissionGroup(
                app_id=app_id,
                key=payload.key,
                name=payload.name,
                description=payload.description,
                parent=parent,
                depth=parent.depth + 1,
                display_order=payload.display_order,
                is_active=payload.is_active,
            )
        case None:
            return PermissionGroup(
                app_id=app_id,
                key=payload.key,
                name=payload.name,
                description=payload.description,
                parent=None,
                depth=1,
                display_order=payload.display_order,
                is_active=payload.is_active,
            )
        case JsonResponse() as response:
            return response


def _update_permission_group(
    request: HttpRequest,
    app_key: str,
    group_key: str | None = None,
) -> JsonResponse:
    match write_context(request, app_key):
        case CatalogWriteContext(app=app, actor=actor):
            pass
        case JsonResponse() as response:
            return response
    match group_update_payload(request, app_key, group_key):
        case PermissionGroupUpdatePayload() as payload:
            pass
        case JsonResponse() as response:
            return response
    group = PermissionGroup.objects.filter(app=app, id=payload.id).first()
    if group is None:
        return semantic_response("权限分组不属于当前 App。")
    match mutate_permission_group(group, payload):
        case None:
            pass
        case JsonResponse() as response:
            return response
    record_catalog_event(
        CatalogEvent(
            app=app,
            actor=actor,
            action="permission_group_updated",
            target_type="permission_group",
            target_id=str(group.id),
            metadata={"permission_group_key": group.key},
        ),
    )
    return json_response({"item": group_item(group)})
