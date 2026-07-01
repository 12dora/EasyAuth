from __future__ import annotations

from http import HTTPStatus

from django.http import HttpRequest, JsonResponse
from pydantic import ValidationError

from easyauth.access_requests.services import (
    AccessRequestService,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
)
from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.responses import error_response as _error_response
from easyauth.api.responses import json_response as _json_response
from easyauth.portal.access_request_payloads import (
    AccessRequestPayload,
    AccessRequestTargetError,
    app_for_key,
    authorization_groups_for_keys,
    direct_grants_for_payloads,
)
from easyauth.portal.api_data import (
    access_request_item,
    access_request_items_for_user,
    current_grant_items_for_user,
    expiring_grant_items_for_user,
)
from easyauth.portal.pagination import PortalPage, paginate_items
from easyauth.portal.request_catalog import request_catalog_payload

type PortalApiResult = UserMirror | JsonResponse

MIN_EXPIRING_DAYS = 1
MAX_EXPIRING_DAYS = 90


def portal_grants(request: HttpRequest) -> JsonResponse:
    match _active_user(request):
        case UserMirror() as user:
            return _page_response(paginate_items(current_grant_items_for_user(user), request.GET))
        case JsonResponse() as response:
            return response


def portal_expiring_grants(request: HttpRequest) -> JsonResponse:
    match _active_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    match _parse_days(request):
        case int() as days:
            return _page_response(
                paginate_items(expiring_grant_items_for_user(user, days=days), request.GET),
            )
        case JsonResponse() as response:
            return response


def portal_access_requests(request: HttpRequest) -> JsonResponse:
    match _active_user(request):
        case UserMirror() as user:
            pass
        case JsonResponse() as response:
            return response
    match request.method:
        case "GET":
            return _page_response(paginate_items(access_request_items_for_user(user), request.GET))
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
        case UserMirror():
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求方法无效。",
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )

    return _json_response(request_catalog_payload())


def _submit_access_request(request: HttpRequest, user: UserMirror) -> JsonResponse:
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
                request_type=payload.request_type,
                grant_type=payload.grant_type,
                grant_expires_at=payload.grant_expires_at,
                reason=payload.reason,
                actor_type="user",
                actor_id=user.authentik_user_id,
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
    return _json_response(
        {"access_request": access_request_item(access_request)},
        status=HTTPStatus.CREATED,
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


def _semantic_error_details(exc: AccessRequestTargetError | AccessRequestSubmissionError) -> dict[
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
    items = _json_objects(page.items)
    return _json_response(
        {"items": items, "data": items, "pagination": _pagination_item(page)},
    )


def _pagination_item(page: PortalPage) -> dict[str, JsonValue]:
    return {
        "page": page.page,
        "page_size": page.page_size,
        "total_items": page.total_items,
        "total_pages": page.total_pages,
    }


def _json_objects(items: tuple[dict[str, JsonValue], ...]) -> list[JsonValue]:
    result: list[JsonValue] = []
    result.extend(items)
    return result
