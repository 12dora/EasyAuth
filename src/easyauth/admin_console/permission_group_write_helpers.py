from __future__ import annotations

from django.db import transaction
from django.http import HttpRequest, JsonResponse

from easyauth.admin_console.catalog_relationships import (
    GroupReferenceInput,
    ResolvedGroupReference,
    resolve_group_reference,
)
from easyauth.admin_console.catalog_write_common import (
    conflict_response,
    parse_payload,
    save_model,
    semantic_response,
)
from easyauth.admin_console.permission_group_descendants import update_descendant_depths
from easyauth.admin_console.permission_group_payloads import (
    PermissionGroupCreatePayload,
    PermissionGroupKeyUpdatePayload,
    PermissionGroupUpdatePayload,
)
from easyauth.applications.models import PermissionGroup


def group_update_payload(
    request: HttpRequest,
    app_key: str,
    group_key: str | None,
) -> PermissionGroupUpdatePayload | JsonResponse:
    if group_key is None:
        return parse_payload(request, PermissionGroupUpdatePayload, "权限分组参数无效。")
    match parse_payload(request, PermissionGroupKeyUpdatePayload, "权限分组参数无效。"):
        case PermissionGroupKeyUpdatePayload() as payload:
            match _group_id(app_key, group_key):
                case int() as group_id:
                    return _key_payload_with_id(payload, group_id)
                case JsonResponse() as response:
                    return response
        case JsonResponse() as response:
            return response


def resolved_parent_reference(
    *,
    app_id: int,
    payload: PermissionGroupCreatePayload | PermissionGroupUpdatePayload,
) -> ResolvedGroupReference | JsonResponse:
    return resolve_group_reference(
        GroupReferenceInput(
            app_id=app_id,
            id_value=payload.parent_id,
            key_value=payload.parent_key,
            id_is_set="parent_id" in payload.model_fields_set,
            key_is_set="parent_key" in payload.model_fields_set,
            missing_message="上级权限分组不属于当前 App。",
        ),
    )


def parent_group(
    *,
    parent_id: int | None,
    app_id: int,
) -> PermissionGroup | JsonResponse | None:
    if parent_id is None:
        return None
    parent = PermissionGroup.objects.filter(id=parent_id, app_id=app_id).first()
    if parent is None:
        return semantic_response("上级权限分组不属于当前 App。")
    return parent


def _group_id(app_key: str, group_key: str) -> int | JsonResponse:
    group = PermissionGroup.objects.filter(app__app_key=app_key, key=group_key).first()
    if group is None:
        return semantic_response("权限分组不属于当前 App。")
    return group.id


def _key_payload_with_id(
    payload: PermissionGroupKeyUpdatePayload,
    group_id: int,
) -> PermissionGroupUpdatePayload:
    data = payload.model_dump(exclude_unset=True)
    data["id"] = group_id
    return PermissionGroupUpdatePayload.model_validate(data)


def mutate_permission_group(
    group: PermissionGroup,
    payload: PermissionGroupUpdatePayload,
) -> JsonResponse | None:
    match resolved_parent_reference(app_id=group.app_id, payload=payload):
        case ResolvedGroupReference(group_id=parent_id, touched=parent_updated):
            pass
        case JsonResponse() as response:
            return response
    match _apply_group_update(group, payload, parent_id=parent_id, parent_updated=parent_updated):
        case None:
            pass
        case JsonResponse() as response:
            return response
    return _save_group_update(group, parent_updated=parent_updated)


def _apply_group_update(
    group: PermissionGroup,
    payload: PermissionGroupUpdatePayload,
    *,
    parent_id: int | None,
    parent_updated: bool,
) -> JsonResponse | None:
    if payload.key is not None and payload.key != group.key:
        if PermissionGroup.objects.filter(app=group.app, key=payload.key).exists():
            return conflict_response("权限分组 key 已存在。")
        group.key = payload.key
    _apply_group_text_fields(group, payload)
    match _apply_parent_update(group, parent_id=parent_id, parent_updated=parent_updated):
        case None:
            pass
        case JsonResponse() as response:
            return response
    if payload.display_order is not None:
        group.display_order = payload.display_order
    if payload.is_active is not None:
        group.is_active = payload.is_active
    return None


def _apply_group_text_fields(
    group: PermissionGroup,
    payload: PermissionGroupUpdatePayload,
) -> None:
    if payload.name is not None:
        group.name = payload.name
    if payload.name_en is not None:
        group.name_en = payload.name_en
    if payload.description is not None:
        group.description = payload.description
    if payload.description_en is not None:
        group.description_en = payload.description_en


def _apply_parent_update(
    group: PermissionGroup,
    *,
    parent_id: int | None,
    parent_updated: bool,
) -> JsonResponse | None:
    if not parent_updated:
        return None
    match parent_group(parent_id=parent_id, app_id=group.app_id):
        case PermissionGroup() as parent:
            group.parent = parent
            group.depth = parent.depth + 1
        case None:
            group.parent = None
            group.depth = 1
        case JsonResponse() as response:
            return response
    return None


def _save_group_update(
    group: PermissionGroup,
    *,
    parent_updated: bool,
) -> JsonResponse | None:
    with transaction.atomic():
        match save_model(group):
            case None:
                pass
            case JsonResponse() as response:
                return response
        if parent_updated:
            match update_descendant_depths(group):
                case None:
                    pass
                case JsonResponse() as response:
                    transaction.set_rollback(True)
                    return response
    return None
