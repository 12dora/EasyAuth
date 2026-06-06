from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from django.utils import timezone

from easyauth.admin_console.catalog_relationships import (
    GroupReferenceInput,
    ResolvedGroupReference,
    resolve_group_reference,
)
from easyauth.admin_console.catalog_write_common import (
    conflict_response,
    parse_payload,
    semantic_response,
)
from easyauth.admin_console.permission_payloads import (
    PermissionCreatePayload,
    PermissionKeyUpdatePayload,
    PermissionUpdatePayload,
)
from easyauth.applications.models import Permission, PermissionGroup


def permission_update_payload(
    request: HttpRequest,
    app_key: str,
    permission_key: str | None,
) -> PermissionUpdatePayload | JsonResponse:
    if permission_key is None:
        return parse_payload(request, PermissionUpdatePayload, "权限参数无效。")
    match parse_payload(request, PermissionKeyUpdatePayload, "权限参数无效。"):
        case PermissionKeyUpdatePayload() as payload:
            match _permission_id(app_key, permission_key):
                case int() as permission_id:
                    data = payload.model_dump(exclude_unset=True)
                    data["id"] = permission_id
                    return PermissionUpdatePayload.model_validate(data)
                case JsonResponse() as response:
                    return response
        case JsonResponse() as response:
            return response


def permission_group(
    *,
    group_id: int | None,
    app_id: int,
) -> PermissionGroup | JsonResponse | None:
    if group_id is None:
        return None
    group = PermissionGroup.objects.filter(id=group_id, app_id=app_id).first()
    if group is None:
        return semantic_response("权限分组不属于当前 App。")
    return group


def resolved_group_reference(
    *,
    app_id: int,
    payload: PermissionCreatePayload | PermissionUpdatePayload,
) -> ResolvedGroupReference | JsonResponse:
    return resolve_group_reference(
        GroupReferenceInput(
            app_id=app_id,
            id_value=payload.group_id,
            key_value=payload.group_key,
            id_is_set="group_id" in payload.model_fields_set,
            key_is_set="group_key" in payload.model_fields_set,
            missing_message="权限分组不属于当前 App。",
        ),
    )


def apply_permission_deprecation(
    permission: Permission,
    payload: PermissionCreatePayload | PermissionUpdatePayload,
) -> None:
    if payload.deprecated_reason is None:
        return
    permission.deprecated_reason = payload.deprecated_reason
    permission.deprecated_at = timezone.now()
    permission.is_active = False


def apply_permission_update(
    permission: Permission,
    payload: PermissionUpdatePayload,
) -> JsonResponse | None:
    if payload.is_active is True and permission.deprecated_at is not None:
        return semantic_response("已废弃权限不能直接重新启用。")
    match _apply_permission_identity_fields(permission, payload):
        case None:
            pass
        case JsonResponse() as response:
            return response
    match resolved_group_reference(app_id=permission.app_id, payload=payload):
        case ResolvedGroupReference(group_id=group_id, touched=group_updated):
            pass
        case JsonResponse() as response:
            return response
    match _apply_group_update(permission, group_id=group_id, group_updated=group_updated):
        case None:
            pass
        case JsonResponse() as response:
            return response
    if payload.is_active is not None:
        permission.is_active = payload.is_active
    apply_permission_deprecation(permission, payload)
    return None


def _apply_permission_identity_fields(
    permission: Permission,
    payload: PermissionUpdatePayload,
) -> JsonResponse | None:
    if payload.key is not None and payload.key != permission.key:
        if Permission.objects.filter(app=permission.app, key=payload.key).exists():
            return conflict_response("权限 key 已存在。")
        permission.key = payload.key
    _apply_permission_text_fields(permission, payload)
    return None


def _apply_permission_text_fields(
    permission: Permission,
    payload: PermissionUpdatePayload,
) -> None:
    if payload.name is not None:
        permission.name = payload.name
    if payload.description is not None:
        permission.description = payload.description


def _apply_group_update(
    permission: Permission,
    *,
    group_id: int | None,
    group_updated: bool,
) -> JsonResponse | None:
    if not group_updated:
        return None
    match permission_group(group_id=group_id, app_id=permission.app_id):
        case PermissionGroup() as group:
            permission.group = group
        case None:
            permission.group = None
        case JsonResponse() as response:
            return response
    return None


def _permission_id(app_key: str, permission_key: str) -> int | JsonResponse:
    permission = Permission.objects.filter(app__app_key=app_key, key=permission_key).first()
    if permission is None:
        return semantic_response("权限不属于当前 App。")
    return permission.id
