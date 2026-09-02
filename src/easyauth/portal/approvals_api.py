from __future__ import annotations

from dataclasses import replace
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final

from django.db import models
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.access_requests.approvals import (
    ApprovalActionError,
    ApprovalDecision,
    approve_access_request,
    loaded_approver_user_ids,
    reject_access_request,
)
from easyauth.access_requests.models import (
    DECISION_ACTOR_USER,
    REQUEST_STATUS_SUBMITTED,
    AccessRequest,
    AccessRequestGroup,
    AccessRequestGroupGrantSnapshot,
)
from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.ordering import parse_ordering
from easyauth.api.pagination import pagination_item, total_pages
from easyauth.api.responses import error_response as _error_response
from easyauth.api.responses import json_response as _json_response
from easyauth.portal.access_request_data import (
    APPROVER_PREFETCH,
    access_request_items,
)
from easyauth.portal.pagination import build_page, page_request

if TYPE_CHECKING:
    from easyauth.portal.pagination import PortalPage

type PortalApiResult = UserMirror | JsonResponse

APPROVAL_STATUS_PENDING = "pending"
APPROVAL_STATUS_PROCESSED = "processed"
PORTAL_APPROVAL_ORDERING: Final[dict[str, str]] = {
    "created_at": "submitted_at",
    "decided_at": "decided_at",
    "app_key": "app__app_key",
    "applicant": "user__name",
}
PORTAL_APPROVAL_PENDING_DEFAULT_ORDER: Final[tuple[str, ...]] = ("submitted_at", "id")
PORTAL_APPROVAL_PROCESSED_DEFAULT_ORDER: Final[tuple[str, ...]] = ("-decided_at", "id")


class _ApprovalDecisionPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    comment: str = Field(default="", max_length=2000)


def portal_approvals(request: HttpRequest) -> JsonResponse:
    match _active_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return _method_not_allowed()
    status = request.GET.get("status", APPROVAL_STATUS_PENDING)
    if status not in {APPROVAL_STATUS_PENDING, APPROVAL_STATUS_PROCESSED}:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "status 必须为 pending 或 processed。",
            {"status": status},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    default_order = (
        PORTAL_APPROVAL_PENDING_DEFAULT_ORDER
        if status == APPROVAL_STATUS_PENDING
        else PORTAL_APPROVAL_PROCESSED_DEFAULT_ORDER
    )
    match parse_ordering(request, PORTAL_APPROVAL_ORDERING, default_order):
        case JsonResponse() as response:
            return response
        case tuple() as ordering:
            pass
    return _page_response(_approval_page(user, request, status=status, ordering=ordering))


def portal_approval_detail(request: HttpRequest, request_id: int) -> JsonResponse:
    match _active_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return _method_not_allowed()
    access_request = _visible_approval(user, request_id)
    if access_request is None:
        return _not_found_response()
    return _json_response({"approval": _approval_item(access_request)})


def portal_approval_approve(request: HttpRequest, request_id: int) -> JsonResponse:
    return _decide(request, request_id, action="approve")


def portal_approval_reject(request: HttpRequest, request_id: int) -> JsonResponse:
    return _decide(request, request_id, action="reject")


def _decide(request: HttpRequest, request_id: int, *, action: str) -> JsonResponse:
    match _active_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return _method_not_allowed()
    try:
        payload = _ApprovalDecisionPayload.model_validate_json(request.body or b"{}")
    except ValidationError as exc:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    decision = ApprovalDecision(
        actor_type=DECISION_ACTOR_USER,
        actor_id=user.authentik_user_id,
        comment=payload.comment,
    )
    try:
        if action == "approve":
            access_request = approve_access_request(request_id=request_id, decision=decision)
        else:
            access_request = reject_access_request(request_id=request_id, decision=decision)
    except ApprovalActionError as exc:
        return _approval_error_response(exc)
    return _json_response({"approval": _approval_item(access_request)})


def _approval_error_response(error: ApprovalActionError) -> JsonResponse:
    match error.kind:
        case "not_found":
            return _error_response(
                ErrorCode.NOT_FOUND,
                error.message,
                status=HTTPStatus.NOT_FOUND,
            )
        case "not_approver":
            # 对非审批人隐藏申请是否存在: 与 not_found 同层返回 404 会泄露更少,
            # 但明确 403 更符合"看得到入口却越权"的真实语义; 待办列表本就只含本人待办。
            return _error_response(
                ErrorCode.PERMISSION_DENIED,
                error.message,
                status=HTTPStatus.FORBIDDEN,
            )
        case "conflict" | "application_conflict":
            return _error_response(
                ErrorCode.CONFLICT,
                error.message,
                error.details,
                status=HTTPStatus.CONFLICT,
            )
        case "comment_required" | "validation_error":
            return _error_response(
                ErrorCode.VALIDATION_ERROR,
                error.message,
                error.details,
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        case "application_error":
            details = dict(error.details)
            request_id = details.get("request_id")
            if isinstance(request_id, int):
                access_request = (
                    AccessRequest.objects.select_related("user", "app")
                    .prefetch_related(APPROVER_PREFETCH)
                    .filter(id=request_id)
                    .first()
                )
                if access_request is not None:
                    details["approval"] = _approval_item(access_request)
            return _error_response(
                ErrorCode.SEMANTIC_VALIDATION_ERROR,
                error.message,
                details,
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        case _:
            return _error_response(
                ErrorCode.VALIDATION_ERROR,
                error.message,
                error.details,
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )


def _approval_page(
    user: UserMirror,
    request: HttpRequest,
    *,
    status: str,
    ordering: tuple[str, ...],
) -> PortalPage:
    page = page_request(request.GET)
    if status == APPROVAL_STATUS_PENDING:
        visible = (
            AccessRequest.objects.select_related("user", "app")
            .prefetch_related(APPROVER_PREFETCH)
            .filter(
                status=REQUEST_STATUS_SUBMITTED,
                approver_assignments__approver=user,
            )
            .distinct()
        )
    else:
        visible = (
            AccessRequest.objects.select_related("user", "app")
            .prefetch_related(APPROVER_PREFETCH)
            .filter(decided_by=user.authentik_user_id)
        )
    visible = visible.order_by(*ordering)
    total_items = visible.count()
    last_page = max(total_pages(total_items=total_items, page_size=page.page_size), 1)
    if page.page > last_page:
        page = replace(page, page=last_page)
    page_rows = tuple(visible[page.start : page.stop])
    serialized_items = access_request_items(page_rows)
    authorization_groups_by_id = _approval_authorization_groups_by_request_id(page_rows)
    items = tuple(
        _approval_item_from_serialized(
            access_request,
            item,
            authorization_groups=authorization_groups_by_id[access_request.id],
        )
        for access_request, item in zip(page_rows, serialized_items, strict=True)
    )
    return build_page(items, request=page, total_items=total_items)


def _visible_approval(user: UserMirror, request_id: int) -> AccessRequest | None:
    return (
        AccessRequest.objects.select_related("user", "app")
        .prefetch_related(APPROVER_PREFETCH)
        .filter(id=request_id)
        .filter(
            models.Q(approver_assignments__approver=user)
            | models.Q(decided_by=user.authentik_user_id),
        )
        .distinct()
        .first()
    )


def _approval_item(access_request: AccessRequest) -> dict[str, JsonValue]:
    prefetched = (
        AccessRequest.objects.select_related("user", "app")
        .prefetch_related(APPROVER_PREFETCH)
        .get(pk=access_request.id)
    )
    (item,) = access_request_items((prefetched,))
    return _approval_item_from_serialized(
        prefetched,
        item,
        authorization_groups=_approval_authorization_groups(prefetched),
    )


def _approval_item_from_serialized(
    access_request: AccessRequest,
    item: dict[str, JsonValue],
    *,
    authorization_groups: list[JsonValue],
) -> dict[str, JsonValue]:
    item["authorization_groups"] = authorization_groups
    applicant = access_request.user
    item["applicant"] = {
        "user_id": applicant.authentik_user_id,
        "name": applicant.name,
        "email": applicant.email,
        "department": applicant.department,
    }
    approver_ids: list[JsonValue] = []
    approver_ids.extend(loaded_approver_user_ids(access_request))
    item["approver_user_ids"] = approver_ids
    item["decided_by"] = access_request.decided_by
    item["decided_at"] = datetime_value(access_request.decided_at)
    return item


def _approval_authorization_groups(access_request: AccessRequest) -> list[JsonValue]:
    return _approval_authorization_groups_by_request_id((access_request,))[access_request.id]


def _approval_authorization_groups_by_request_id(
    access_requests: tuple[AccessRequest, ...],
) -> dict[int, list[JsonValue]]:
    request_ids = tuple(access_request.id for access_request in access_requests)
    snapshots_by_request_id = _snapshots_by_request_id(request_ids)
    missing_snapshot_ids = tuple(
        request_id for request_id in request_ids if not snapshots_by_request_id[request_id]
    )
    live_groups_by_request_id = _live_authorization_groups_by_request_id(missing_snapshot_ids)
    groups: dict[int, list[JsonValue]] = {}
    for request_id in request_ids:
        snapshot_items = snapshots_by_request_id[request_id]
        if snapshot_items:
            groups[request_id] = _snapshot_authorization_groups(snapshot_items)
        else:
            groups[request_id] = live_groups_by_request_id.get(request_id, [])
    return groups


def _snapshots_by_request_id(
    request_ids: tuple[int, ...],
) -> dict[int, list[AccessRequestGroupGrantSnapshot]]:
    snapshots_by_request_id: dict[int, list[AccessRequestGroupGrantSnapshot]] = {
        request_id: [] for request_id in request_ids
    }
    if not request_ids:
        return snapshots_by_request_id
    snapshots = AccessRequestGroupGrantSnapshot.objects.filter(
        access_request_id__in=request_ids,
    ).order_by(
        "access_request_id",
        "authorization_group_key",
        "permission_key",
        "scope_key",
    )
    for snapshot in snapshots:
        snapshots_by_request_id.setdefault(snapshot.access_request_id, []).append(snapshot)
    return snapshots_by_request_id


def _live_authorization_groups_by_request_id(
    request_ids: tuple[int, ...],
) -> dict[int, list[JsonValue]]:
    if not request_ids:
        return {}
    group_items_by_request_id: dict[int, dict[str, dict[str, JsonValue]]] = {
        request_id: {} for request_id in request_ids
    }
    for link in (
        AccessRequestGroup.objects.select_related("authorization_group")
        .filter(access_request_id__in=request_ids)
        .order_by("access_request_id", "authorization_group__key")
    ):
        group = link.authorization_group
        group_items_by_request_id.setdefault(link.access_request_id, {})[group.key] = {
            "key": group.key,
            "kind": group.kind,
            "name": group.name,
            "grants": [],
        }
    return {
        request_id: list(group_items.values())
        for request_id, group_items in group_items_by_request_id.items()
    }


def _snapshot_authorization_groups(
    snapshots: list[AccessRequestGroupGrantSnapshot],
) -> list[JsonValue]:
    group_items: dict[str, dict[str, JsonValue]] = {}
    for snapshot in snapshots:
        item = group_items.setdefault(
            snapshot.authorization_group_key,
            {
                "key": snapshot.authorization_group_key,
                "kind": snapshot.authorization_group_kind,
                "name": snapshot.authorization_group_name,
                "grants": [],
            },
        )
        grants = item["grants"]
        if not isinstance(grants, list):
            message = "approval group grants shape is invalid"
            raise TypeError(message)
        grants.append(
            {
                "permission": snapshot.permission_key,
                "permission_name": snapshot.permission_name,
                "scope": snapshot.scope_key,
            },
        )
    return list(group_items.values())


def _active_user(request: HttpRequest) -> PortalApiResult:
    authentik_user_id = request.session.get(AUTHENTIK_SESSION_KEY)
    if not isinstance(authentik_user_id, str):
        return _unauthorized_response()
    user = UserMirror.objects.filter(
        authentik_user_id=authentik_user_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    if user is None:
        request.session.pop(AUTHENTIK_SESSION_KEY, None)
        return _unauthorized_response()
    return user


def _unauthorized_response() -> JsonResponse:
    return _error_response(
        ErrorCode.AUTHENTICATION_FAILED,
        "员工门户登录已失效。",
        status=HTTPStatus.UNAUTHORIZED,
    )


def _not_found_response() -> JsonResponse:
    return _error_response(
        ErrorCode.NOT_FOUND,
        "申请不存在或无权查看。",
        status=HTTPStatus.NOT_FOUND,
    )


def _method_not_allowed() -> JsonResponse:
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        "请求方法无效。",
        status=HTTPStatus.METHOD_NOT_ALLOWED,
    )


def _page_response(page: PortalPage) -> JsonResponse:
    items: list[JsonValue] = []
    items.extend(page.items)
    return _json_response({"data": items, "pagination": pagination_item(page)})
