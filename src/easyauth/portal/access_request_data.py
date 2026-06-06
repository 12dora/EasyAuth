from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.access_requests.models import (
    AccessRequest,
    AccessRequestPermission,
    AccessRequestRole,
)
from easyauth.api.errors import JsonValue

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.accounts.models import UserMirror

type PortalJsonObject = dict[str, JsonValue]


def access_request_items_for_user(user: UserMirror) -> tuple[PortalJsonObject, ...]:
    access_requests = tuple(
        AccessRequest.objects.select_related("app")
        .filter(user=user)
        .order_by("-submitted_at", "id"),
    )
    request_ids = tuple(access_request.id for access_request in access_requests)
    role_keys, role_names = _request_roles_by_request_id(request_ids)
    permission_keys, permission_names = _request_permissions_by_request_id(request_ids)
    return tuple(
        _access_request_item(
            access_request,
            role_keys=role_keys.get(access_request.id, ()),
            role_names=role_names.get(access_request.id, ()),
            permission_keys=permission_keys.get(access_request.id, ()),
            permission_names=permission_names.get(access_request.id, ()),
        )
        for access_request in access_requests
    )


def access_request_item(access_request: AccessRequest) -> PortalJsonObject:
    role_keys, role_names = _request_roles_by_request_id((access_request.id,))
    permission_keys, permission_names = _request_permissions_by_request_id((access_request.id,))
    return _access_request_item(
        access_request,
        role_keys=role_keys.get(access_request.id, ()),
        role_names=role_names.get(access_request.id, ()),
        permission_keys=permission_keys.get(access_request.id, ()),
        permission_names=permission_names.get(access_request.id, ()),
    )


def _request_roles_by_request_id(
    request_ids: tuple[int, ...],
) -> tuple[dict[int, tuple[str, ...]], dict[int, tuple[str, ...]]]:
    role_keys: dict[int, list[str]] = {request_id: [] for request_id in request_ids}
    role_names: dict[int, list[str]] = {request_id: [] for request_id in request_ids}
    links = (
        AccessRequestRole.objects.select_related("role")
        .filter(access_request_id__in=request_ids)
        .order_by("access_request_id", "role__key")
    )
    for link in links:
        role_keys.setdefault(link.access_request_id, []).append(link.role.key)
        role_names.setdefault(link.access_request_id, []).append(link.role.name)
    return (
        {request_id: tuple(keys) for request_id, keys in role_keys.items()},
        {request_id: tuple(names) for request_id, names in role_names.items()},
    )


def _request_permissions_by_request_id(
    request_ids: tuple[int, ...],
) -> tuple[dict[int, tuple[str, ...]], dict[int, tuple[str, ...]]]:
    permission_keys: dict[int, list[str]] = {request_id: [] for request_id in request_ids}
    permission_names: dict[int, list[str]] = {request_id: [] for request_id in request_ids}
    links = (
        AccessRequestPermission.objects.select_related("access_request", "permission")
        .filter(access_request_id__in=request_ids)
        .order_by("access_request_id", "permission__key")
    )
    for link in links:
        request_id = link.access_request.id
        permission_keys.setdefault(request_id, []).append(link.permission.key)
        permission_names.setdefault(request_id, []).append(link.permission.name)
    return (
        {request_id: tuple(keys) for request_id, keys in permission_keys.items()},
        {request_id: tuple(names) for request_id, names in permission_names.items()},
    )


def _access_request_item(
    access_request: AccessRequest,
    *,
    role_keys: tuple[str, ...],
    role_names: tuple[str, ...],
    permission_keys: tuple[str, ...],
    permission_names: tuple[str, ...],
) -> PortalJsonObject:
    return {
        "id": access_request.id,
        "app_key": access_request.app.app_key,
        "app_name": access_request.app.name,
        "request_type": access_request.request_type,
        "status": access_request.status,
        "status_label": _status_label(access_request.status),
        "grant_type": access_request.grant_type,
        "grant_expires_at": _datetime_value(access_request.grant_expires_at),
        "reason": access_request.reason,
        "submitted_at": access_request.submitted_at.isoformat(),
        "roles": _json_strings(role_keys),
        "role_names": _json_strings(role_names),
        "permissions": _json_strings(permission_keys),
        "permission_names": _json_strings(permission_names),
    }


def _status_label(status: str) -> str:
    match status:
        case "submitted":
            return "等待审批"
        case "approved":
            return "审批已通过, 等待授权落库"
        case "grant_applied":
            return "授权已落库, 权限已生效"
        case "rejected":
            return "已拒绝"
        case "grant_failed":
            return "授权落库失败"
        case _:
            return "未知"


def _datetime_value(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _json_strings(values: tuple[str, ...]) -> list[JsonValue]:
    result: list[JsonValue] = []
    result.extend(values)
    return result
