from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.access_requests.models import (
    AccessRequest,
    AccessRequestGroup,
    AccessRequestPermission,
)
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import JsonValue
from easyauth.portal.pagination import PortalPage, build_page, page_request
from easyauth.portal.status_text import status_label

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import QueryDict

    from easyauth.accounts.models import UserMirror

type PortalJsonObject = dict[str, JsonValue]


def _access_requests_queryset(user: UserMirror) -> QuerySet[AccessRequest]:
    return (
        AccessRequest.objects.select_related("app")
        .filter(user=user)
        .order_by("-submitted_at", "id")
    )


def _items_for_access_requests(
    access_requests: tuple[AccessRequest, ...],
) -> tuple[PortalJsonObject, ...]:
    # 只按传入(可能已分页)的这批 id 批量 hydrate group/direct grant, 不做全量载入。
    request_ids = tuple(access_request.id for access_request in access_requests)
    group_items = _request_groups_by_request_id(request_ids)
    direct_grant_items = _request_direct_grants_by_request_id(request_ids)
    return tuple(
        _access_request_item(
            access_request,
            group_items=group_items.get(access_request.id, ()),
            direct_grant_items=direct_grant_items.get(access_request.id, ()),
        )
        for access_request in access_requests
    )


def access_request_items_for_user(user: UserMirror) -> tuple[PortalJsonObject, ...]:
    return _items_for_access_requests(tuple(_access_requests_queryset(user)))


def access_request_page_for_user(user: UserMirror, query: QueryDict) -> PortalPage:
    # 分页下推到 queryset: 先 count + 切片, 再只对当前页 hydrate, 不再全量载入内存(BF-6)。
    queryset = _access_requests_queryset(user)
    request = page_request(query)
    total_items = queryset.count()
    access_requests = tuple(queryset[request.start : request.stop])
    return build_page(
        _items_for_access_requests(access_requests),
        request=request,
        total_items=total_items,
    )


def access_request_item(access_request: AccessRequest) -> PortalJsonObject:
    group_items = _request_groups_by_request_id((access_request.id,))
    direct_grant_items = _request_direct_grants_by_request_id((access_request.id,))
    return _access_request_item(
        access_request,
        group_items=group_items.get(access_request.id, ()),
        direct_grant_items=direct_grant_items.get(access_request.id, ()),
    )


def _request_groups_by_request_id(
    request_ids: tuple[int, ...],
) -> dict[int, tuple[dict[str, JsonValue], ...]]:
    group_items: dict[int, list[dict[str, JsonValue]]] = {
        request_id: [] for request_id in request_ids
    }
    links = (
        AccessRequestGroup.objects.select_related("authorization_group")
        .filter(access_request_id__in=request_ids)
        .order_by("access_request_id", "authorization_group__key")
    )
    for link in links:
        group = link.authorization_group
        group_items.setdefault(link.access_request_id, []).append(
            {"key": group.key, "kind": group.kind, "name": group.name},
        )
    return {request_id: tuple(items) for request_id, items in group_items.items()}


def _request_direct_grants_by_request_id(
    request_ids: tuple[int, ...],
) -> dict[int, tuple[dict[str, JsonValue], ...]]:
    direct_grant_items: dict[int, list[dict[str, JsonValue]]] = {
        request_id: [] for request_id in request_ids
    }
    links = (
        AccessRequestPermission.objects.select_related("access_request", "permission")
        .filter(access_request_id__in=request_ids)
        .order_by("access_request_id", "permission__key", "scope_key")
    )
    for link in links:
        request_id = link.access_request.id
        direct_grant_items.setdefault(request_id, []).append(
            {
                "permission": link.permission.key,
                "permission_name": link.permission.name,
                "scope": link.scope_key,
            },
        )
    return {request_id: tuple(items) for request_id, items in direct_grant_items.items()}


def _access_request_item(
    access_request: AccessRequest,
    *,
    group_items: tuple[dict[str, JsonValue], ...],
    direct_grant_items: tuple[dict[str, JsonValue], ...],
) -> PortalJsonObject:
    return {
        "id": access_request.id,
        "app_key": access_request.app.app_key,
        "app_name": access_request.app.name,
        "request_type": access_request.request_type,
        "status": access_request.status,
        "status_label": status_label(access_request.status),
        "grant_type": access_request.grant_type,
        "grant_expires_at": datetime_value(access_request.grant_expires_at),
        "reason": access_request.reason,
        "submitted_at": access_request.submitted_at.isoformat(),
        "authorization_groups": _json_objects(group_items),
        "direct_grants": _json_objects(direct_grant_items),
    }


def _json_objects(values: tuple[dict[str, JsonValue], ...]) -> list[JsonValue]:
    result: list[JsonValue] = []
    result.extend(values)
    return result
