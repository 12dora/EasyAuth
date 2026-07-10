from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.access_requests.approvals import (
    ApprovalActionError,
    ApprovalDecision,
    approve_access_request,
    approver_is_authorized,
    reject_access_request,
)
from easyauth.access_requests.models import (
    DECISION_ACTOR_USER,
    REQUEST_STATUS_SUBMITTED,
    AccessRequest,
    AccessRequestGroup,
)
from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.pagination import pagination_item
from easyauth.api.responses import error_response as _error_response
from easyauth.api.responses import json_response as _json_response
from easyauth.applications.models import AuthorizationGroupGrant
from easyauth.portal.access_request_data import access_request_item
from easyauth.portal.pagination import build_page, page_request

if TYPE_CHECKING:
    from easyauth.portal.pagination import PortalPage

type PortalApiResult = UserMirror | JsonResponse

APPROVAL_STATUS_PENDING = "pending"
APPROVAL_STATUS_PROCESSED = "processed"


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
    return _page_response(_approval_page(user, request, status=status))


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
        case "conflict":
            return _error_response(
                ErrorCode.SEMANTIC_VALIDATION_ERROR,
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


def _approval_page(user: UserMirror, request: HttpRequest, *, status: str) -> PortalPage:
    # approver_user_ids 是 JSON 数组且部署库为 SQLite(不支持 __contains):
    # 待办集按 submitted 全集在 Python 侧过滤成员资格; 待办体量与在途申请数同阶, 可控。
    if status == APPROVAL_STATUS_PENDING:
        candidates = (
            AccessRequest.objects.select_related("user", "app")
            .filter(status=REQUEST_STATUS_SUBMITTED)
            .order_by("submitted_at", "id")
        )
        visible = [
            access_request
            for access_request in candidates
            if approver_is_authorized(access_request, user.authentik_user_id)
        ]
    else:
        visible = list(
            AccessRequest.objects.select_related("user", "app")
            .filter(decided_by=user.authentik_user_id)
            .order_by("-decided_at", "id"),
        )
    page = page_request(request.GET)
    items = tuple(
        _approval_item(access_request) for access_request in visible[page.start : page.stop]
    )
    return build_page(items, request=page, total_items=len(visible))


def _visible_approval(user: UserMirror, request_id: int) -> AccessRequest | None:
    access_request = (
        AccessRequest.objects.select_related("user", "app").filter(id=request_id).first()
    )
    if access_request is None:
        return None
    if approver_is_authorized(access_request, user.authentik_user_id):
        return access_request
    if access_request.decided_by == user.authentik_user_id:
        return access_request
    return None


def _approval_item(access_request: AccessRequest) -> dict[str, JsonValue]:
    item = access_request_item(access_request)
    item["authorization_groups"] = _approval_authorization_groups(access_request)
    applicant = access_request.user
    item["applicant"] = {
        "user_id": applicant.authentik_user_id,
        "name": applicant.name,
        "email": applicant.email,
        "department": applicant.department,
    }
    approver_ids: list[JsonValue] = [
        user_id for user_id in access_request.approver_user_ids if user_id
    ]
    item["approver_user_ids"] = approver_ids
    item["decided_by"] = access_request.decided_by
    item["decided_at"] = datetime_value(access_request.decided_at)
    return item


def _approval_authorization_groups(access_request: AccessRequest) -> list[JsonValue]:
    links = (
        AccessRequestGroup.objects.select_related("authorization_group")
        .filter(access_request=access_request)
        .order_by("authorization_group__key")
    )
    groups: list[JsonValue] = []
    for link in links:
        group = link.authorization_group
        grants = (
            AuthorizationGroupGrant.objects.select_related("permission")
            .filter(authorization_group=group, is_active=True)
            .order_by("permission__key", "scope_key")
        )
        grant_items: list[JsonValue] = [
            {
                "permission": grant.permission.key,
                "permission_name": grant.permission.name,
                "scope": grant.scope_key,
            }
            for grant in grants
        ]
        groups.append(
            {
                "key": group.key,
                "kind": group.kind,
                "name": group.name,
                "grants": grant_items,
            },
        )
    return groups


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
