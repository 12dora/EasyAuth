from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Final

from django.http import HttpRequest, JsonResponse
from pydantic import ValidationError

from easyauth.access_requests.approvals import (
    ApprovalActionError,
    withdraw_access_request,
)
from easyauth.access_requests.services import (
    IDEMPOTENCY_KEY_MAX_LENGTH,
    AccessRequestIdempotencyConflictError,
    AccessRequestService,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
)
from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.ordering import parse_ordering
from easyauth.api.pagination import pagination_item
from easyauth.api.responses import error_response as _error_response
from easyauth.api.responses import json_response as _json_response
from easyauth.grants.managed_users import ManagedUsersResolutionUnavailableError
from easyauth.portal.access_request_payloads import (
    AccessRequestPayload,
    AccessRequestTargetError,
    app_for_key,
    authorization_groups_for_keys,
    direct_grants_for_payloads,
)
from easyauth.portal.api_data import (
    access_request_item,
    access_request_page_for_user,
    current_grant_page_for_user,
    expiring_grant_page_for_user,
)
from easyauth.portal.request_catalog import request_catalog_payload

if TYPE_CHECKING:
    from easyauth.portal.pagination import PortalPage

type PortalApiResult = UserMirror | JsonResponse

MIN_EXPIRING_DAYS = 1
MAX_EXPIRING_DAYS = 90
PORTAL_GRANT_ORDERING: Final[dict[str, str]] = {
    "app_key": "app__app_key",
    "expires_at": "expires_at",
    "created_at": "created_at",
}
PORTAL_GRANT_DEFAULT_ORDER: Final[tuple[str, ...]] = ("app__app_key", "id")
PORTAL_ACCESS_REQUEST_ORDERING: Final[dict[str, str]] = {
    "created_at": "submitted_at",
    "status": "status",
    "app_key": "app__app_key",
    "expires_at": "grant_expires_at",
}
PORTAL_ACCESS_REQUEST_DEFAULT_ORDER: Final[tuple[str, ...]] = ("-submitted_at", "id")


@dataclass(frozen=True, slots=True)
class _PaginationAdapter:
    page: int
    page_size: int
    total_items: int
    total_pages: int


def portal_grants(request: HttpRequest) -> JsonResponse:
    match _active_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    match parse_ordering(request, PORTAL_GRANT_ORDERING, PORTAL_GRANT_DEFAULT_ORDER):
        case JsonResponse() as response:
            return response
        case tuple() as ordering:
            pass
    try:
        page = current_grant_page_for_user(user, request.GET, ordering=ordering)
    except ManagedUsersResolutionUnavailableError as error:
        return _directory_unavailable_response(error)
    except ValueError as error:
        return _query_validation_response(str(error))
    return _page_response(page)


def portal_expiring_grants(request: HttpRequest) -> JsonResponse:
    match _active_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    match _parse_days(request):
        case int() as days:
            pass
        case JsonResponse() as response:
            return response
    match parse_ordering(request, PORTAL_GRANT_ORDERING, PORTAL_GRANT_DEFAULT_ORDER):
        case JsonResponse() as response:
            return response
        case tuple() as ordering:
            pass
    try:
        page = expiring_grant_page_for_user(user, request.GET, days=days, ordering=ordering)
    except ManagedUsersResolutionUnavailableError as error:
        return _directory_unavailable_response(error)
    except ValueError as error:
        return _query_validation_response(str(error))
    return _page_response(page)


def _directory_unavailable_response(error: ManagedUsersResolutionUnavailableError) -> JsonResponse:
    return _error_response(
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        str(error),
        status=HTTPStatus.SERVICE_UNAVAILABLE,
    )


def _query_validation_response(message: str) -> JsonResponse:
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def portal_access_requests(request: HttpRequest) -> JsonResponse:
    match _active_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    match request.method:
        case "GET":
            match parse_ordering(
                request,
                PORTAL_ACCESS_REQUEST_ORDERING,
                PORTAL_ACCESS_REQUEST_DEFAULT_ORDER,
            ):
                case JsonResponse() as response:
                    return response
                case tuple() as ordering:
                    pass
            try:
                return _page_response(
                    access_request_page_for_user(user, request.GET, ordering=ordering),
                )
            except ValueError as error:
                return _query_validation_response(str(error))
        case "POST":
            return _submit_access_request(request, user)
        case _:
            return _error_response(
                ErrorCode.VALIDATION_ERROR,
                "请求方法无效。",
                status=HTTPStatus.METHOD_NOT_ALLOWED,
            )


def portal_request_catalog(request: HttpRequest) -> JsonResponse:
    match _active_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求方法无效。",
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )

    return _json_response(request_catalog_payload(user))


def portal_access_request_withdraw(request: HttpRequest, request_id: int) -> JsonResponse:
    """申请人撤回本人的待审批申请。"""
    match _active_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求方法无效。",
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )
    try:
        access_request = withdraw_access_request(
            request_id=request_id,
            actor_user_id=user.authentik_user_id,
        )
    except ApprovalActionError as exc:
        return _withdraw_error_response(exc)
    return _json_response({"access_request": access_request_item(access_request)})


def _withdraw_error_response(error: ApprovalActionError) -> JsonResponse:
    match error.kind:
        case "not_found" | "not_owner":
            return _error_response(
                ErrorCode.NOT_FOUND,
                "申请不存在或无权撤回。",
                status=HTTPStatus.NOT_FOUND,
            )
        case "conflict":
            return _error_response(
                ErrorCode.SEMANTIC_VALIDATION_ERROR,
                error.message,
                error.details,
                status=HTTPStatus.CONFLICT,
            )
        case _:
            return _error_response(
                ErrorCode.VALIDATION_ERROR,
                error.message,
                error.details,
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )


def _submit_access_request(request: HttpRequest, user: UserMirror) -> JsonResponse:
    match _idempotency_key(request):
        case str() as idempotency_key:
            pass
        case JsonResponse() as response:
            return response
    try:
        payload = AccessRequestPayload.model_validate_json(request.body)
        app = app_for_key(payload.app_key)
        authorization_groups = authorization_groups_for_keys(
            app=app,
            authorization_group_keys=payload.authorization_group_keys,
        )
        direct_grants = direct_grants_for_payloads(app=app, direct_grants=payload.direct_grants)
        access_request = AccessRequestService.submit_access_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                authorization_groups=authorization_groups,
                direct_grants=direct_grants,
                approver_user_ids=payload.approver_user_ids,
                request_type=payload.request_type,
                base_grant_id=payload.base_grant_id,
                base_grant_revision=payload.base_grant_revision,
                grant_type=payload.grant_type,
                grant_expires_at=payload.grant_expires_at,
                reason=payload.reason,
                actor_type="user",
                actor_id=user.authentik_user_id,
                idempotency_key=idempotency_key,
            ),
        )
    except ValidationError as exc:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    except (AccessRequestTargetError, AccessRequestSubmissionError) as exc:
        return _error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            str(exc),
            _semantic_error_details(exc),
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    except AccessRequestIdempotencyConflictError as exc:
        return _error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            str(exc),
            {"idempotency_key": idempotency_key},
            status=HTTPStatus.CONFLICT,
        )
    return _json_response(
        {"access_request": access_request_item(access_request)},
        status=HTTPStatus.CREATED,
    )


def _idempotency_key(request: HttpRequest) -> str | JsonResponse:
    value = request.headers.get("Idempotency-Key", "")
    if value and value == value.strip() and len(value) <= IDEMPOTENCY_KEY_MAX_LENGTH:
        return value
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        "Idempotency-Key 必须为非空且不超过 128 个字符。",
        {"idempotency_key": value},
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def _active_user(request: HttpRequest) -> PortalApiResult:
    authentik_user_id = request.session.get(AUTHENTIK_SESSION_KEY)
    if not isinstance(authentik_user_id, str):
        return _error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            "员工门户登录已失效。",
            status=HTTPStatus.UNAUTHORIZED,
        )
    user = UserMirror.objects.filter(
        authentik_user_id=authentik_user_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    if user is None:
        request.session.pop(AUTHENTIK_SESSION_KEY, None)
        return _error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            "员工门户登录已失效。",
            status=HTTPStatus.UNAUTHORIZED,
        )
    return user


def _parse_days(request: HttpRequest) -> int | JsonResponse:
    raw_days = request.GET.get("days", "14")
    try:
        days = int(raw_days)
    except ValueError:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "days 必须是整数。",
            {"days": raw_days},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    if days < MIN_EXPIRING_DAYS or days > MAX_EXPIRING_DAYS:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            f"days 必须在 {MIN_EXPIRING_DAYS} 到 {MAX_EXPIRING_DAYS} 之间。",
            {"days": days},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    return days


def _semantic_error_details(
    exc: AccessRequestTargetError | AccessRequestSubmissionError,
) -> dict[
    str,
    JsonValue,
]:
    match exc:
        case AccessRequestTargetError(details=details):
            return details
        case AccessRequestSubmissionError(messages=messages):
            return {"messages": _json_strings(messages)}


def _json_strings(values: tuple[str, ...]) -> list[JsonValue]:
    result: list[JsonValue] = []
    result.extend(values)
    return result


def _page_response(page: PortalPage) -> JsonResponse:
    return _json_response(
        {"data": _json_objects(page.items), "pagination": pagination_item(_pagination(page))},
    )


def _pagination(page: PortalPage) -> _PaginationAdapter:
    return _PaginationAdapter(
        page=page.page,
        page_size=page.page_size,
        total_items=page.total_items,
        total_pages=page.total_pages,
    )


def _json_objects(items: tuple[dict[str, JsonValue], ...]) -> list[JsonValue]:
    result: list[JsonValue] = []
    result.extend(items)
    return result
