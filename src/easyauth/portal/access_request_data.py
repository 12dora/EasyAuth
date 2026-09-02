from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, override

from django.db.models import Prefetch

from easyauth.access_requests.models import (
    DECISION_ACTOR_USER,
    REQUEST_STATUS_SUBMITTED,
    AccessRequest,
    AccessRequestApprover,
    AccessRequestGroup,
    AccessRequestPermission,
)
from easyauth.accounts.models import UserMirror
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import JsonValue
from easyauth.portal.pagination import PortalPage, build_page, page_request
from easyauth.portal.request_catalog_approvers import approver_option
from easyauth.portal.status_text import status_label

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import QueryDict

type PortalJsonObject = dict[str, JsonValue]

APPROVER_PREFETCH: Final = Prefetch(
    "approver_assignments",
    queryset=AccessRequestApprover.objects.select_related("approver"),
    to_attr="loaded_approver_assignments",
)


@dataclass(frozen=True, slots=True)
class AccessRequestDecisionActorMissingError(RuntimeError):
    missing_user_ids: tuple[str, ...]

    @override
    def __str__(self) -> str:
        missing = list(self.missing_user_ids)
        return f"user-actor access request decisions are missing UserMirror rows: {missing}"


def _access_requests_queryset(user: UserMirror) -> QuerySet[AccessRequest]:
    return (
        AccessRequest.objects.select_related("app")
        .prefetch_related(APPROVER_PREFETCH)
        .filter(user=user)
        .order_by("-submitted_at", "id")
    )


def access_request_items(
    access_requests: tuple[AccessRequest, ...],
) -> tuple[PortalJsonObject, ...]:
    # 只按传入(可能已分页)的这批 id 批量 hydrate group/direct grant/决定人姓名, 不做全量载入。
    request_ids = tuple(access_request.id for access_request in access_requests)
    group_items = _request_groups_by_request_id(request_ids)
    direct_grant_items = _request_direct_grants_by_request_id(request_ids)
    decided_by_names = _decided_by_names(access_requests)
    return tuple(
        _access_request_item(
            access_request,
            group_items=group_items.get(access_request.id, ()),
            direct_grant_items=direct_grant_items.get(access_request.id, ()),
            decided_by_name=decided_by_names.get(access_request.id),
        )
        for access_request in access_requests
    )


def access_request_items_for_user(user: UserMirror) -> tuple[PortalJsonObject, ...]:
    return access_request_items(tuple(_access_requests_queryset(user)))


def access_request_page_for_user(
    user: UserMirror,
    query: QueryDict,
    *,
    ordering: tuple[str, ...],
) -> PortalPage:
    # 分页下推到 queryset: 先 count + 切片, 再只对当前页 hydrate, 不再全量载入内存(BF-6)。
    queryset = _access_requests_queryset(user).order_by(*ordering)
    request = page_request(query)
    total_items = queryset.count()
    access_requests = tuple(queryset[request.start : request.stop])
    return build_page(
        access_request_items(access_requests),
        request=request,
        total_items=total_items,
    )


def access_request_item(access_request: AccessRequest) -> PortalJsonObject:
    prefetched = (
        AccessRequest.objects.select_related("app")
        .prefetch_related(APPROVER_PREFETCH)
        .get(pk=access_request.id)
    )
    (item,) = access_request_items((prefetched,))
    return item


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


def _decided_by_names(access_requests: tuple[AccessRequest, ...]) -> dict[int, str]:
    actor_ids = tuple(
        dict.fromkeys(
            access_request.decided_by
            for access_request in access_requests
            if access_request.decision_actor_type == DECISION_ACTOR_USER
        ),
    )
    if not actor_ids:
        return {}
    names_by_user_id = {
        user.authentik_user_id: user.name
        for user in UserMirror.objects.filter(authentik_user_id__in=actor_ids)
    }
    missing_user_ids = tuple(
        actor_id for actor_id in actor_ids if actor_id not in names_by_user_id
    )
    if missing_user_ids:
        raise AccessRequestDecisionActorMissingError(missing_user_ids)
    return {
        access_request.id: names_by_user_id[access_request.decided_by]
        for access_request in access_requests
        if access_request.decision_actor_type == DECISION_ACTOR_USER
    }


def _current_approver_items(
    access_request: AccessRequest,
) -> tuple[dict[str, JsonValue], ...]:
    if access_request.status != REQUEST_STATUS_SUBMITTED:
        return ()
    assignments = sorted(
        access_request.loaded_approver_assignments,
        key=lambda assignment: assignment.id,
    )
    return tuple(approver_option(assignment.approver) for assignment in assignments)


def _access_request_item(
    access_request: AccessRequest,
    *,
    group_items: tuple[dict[str, JsonValue], ...],
    direct_grant_items: tuple[dict[str, JsonValue], ...],
    decided_by_name: str | None,
) -> PortalJsonObject:
    return {
        "id": access_request.id,
        "app_key": access_request.app.app_key,
        "app_name": access_request.app.name,
        "request_type": access_request.request_type,
        "base_grant_id": access_request.base_grant_id,
        "base_grant_revision": access_request.base_grant_revision,
        "status": access_request.status,
        "status_label": status_label(access_request.status),
        "grant_type": access_request.grant_type,
        "grant_expires_at": datetime_value(access_request.grant_expires_at),
        "reason": access_request.reason,
        "submitted_at": access_request.submitted_at.isoformat(),
        "authorization_groups": _json_objects(group_items),
        "direct_grants": _json_objects(direct_grant_items),
        "current_approvers": _json_objects(_current_approver_items(access_request)),
        # 审批决定信息: 申请人可见驳回理由、处理时间、决定人。
        "decided_by": access_request.decided_by,
        "decision_actor_type": access_request.decision_actor_type,
        "decided_by_name": decided_by_name,
        "decided_at": datetime_value(access_request.decided_at),
        "decision_comment": access_request.decision_comment,
    }


def _json_objects(values: tuple[dict[str, JsonValue], ...]) -> list[JsonValue]:
    result: list[JsonValue] = []
    result.extend(values)
    return result
