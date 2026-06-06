from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Annotated, ClassVar, Literal, override

from django.http import HttpRequest, JsonResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from easyauth.access_requests.services import (
    AccessRequestService,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
)
from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.api.errors import ErrorCode, ErrorResponse, JsonValue, build_error_response
from easyauth.applications.models import App, Permission, Role
from easyauth.portal.api_data import (
    access_request_item,
    access_request_items_for_user,
    current_grant_items_for_user,
    expiring_grant_items_for_user,
)
from easyauth.portal.pagination import PortalPage, paginate_items

type RoleKey = Annotated[str, Field(min_length=1, max_length=128)]
type PermissionKey = Annotated[str, Field(min_length=1, max_length=128)]
type GrantType = Literal["permanent", "timed"]
type RequestType = Literal["grant", "change", "revoke", "renew"]
type PortalApiResult = UserMirror | JsonResponse

MIN_EXPIRING_DAYS = 1
MAX_EXPIRING_DAYS = 90
APP_NOT_REQUESTABLE_MESSAGE = "应用当前不可申请。"
ROLE_NOT_REQUESTABLE_MESSAGE = "角色当前不可申请。"
PERMISSION_NOT_REQUESTABLE_MESSAGE = "权限当前不可申请。"


@dataclass(frozen=True, slots=True)
class PortalApiSemanticError(Exception):
    message: str
    details: dict[str, JsonValue]

    @override
    def __str__(self) -> str:
        return self.message


class _AccessRequestPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    app_key: str = Field(min_length=1, max_length=128)
    request_type: RequestType = "grant"
    role_keys: tuple[RoleKey, ...] = Field(default=(), max_length=20)
    permission_keys: tuple[PermissionKey, ...] = Field(default=(), max_length=50)
    grant_type: GrantType
    grant_expires_at: AwareDatetime | None = None
    reason: str = Field(min_length=1, max_length=1000)


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
            return JsonResponse(
                build_error_response(ErrorCode.VALIDATION_ERROR, "请求方法无效。"),
                status=HTTPStatus.METHOD_NOT_ALLOWED,
            )


def _submit_access_request(request: HttpRequest, user: UserMirror) -> JsonResponse:
    try:
        payload = _AccessRequestPayload.model_validate_json(request.body)
        app = _app_for_key(payload.app_key)
        roles = _roles_for_keys(app=app, role_keys=payload.role_keys)
        permissions = _permissions_for_keys(app=app, permission_keys=payload.permission_keys)
        access_request = AccessRequestService.submit_access_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                roles=roles,
                permissions=permissions,
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
    except (PortalApiSemanticError, AccessRequestSubmissionError) as exc:
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


def _app_for_key(app_key: str) -> App:
    app = App.objects.filter(app_key=app_key, is_active=True).first()
    if app is None:
        raise PortalApiSemanticError(APP_NOT_REQUESTABLE_MESSAGE, {"app_key": app_key})
    return app


def _roles_for_keys(*, app: App, role_keys: tuple[str, ...]) -> tuple[Role, ...]:
    role_by_key = {role.key: role for role in Role.objects.filter(app=app, key__in=role_keys)}
    missing_role_keys = tuple(key for key in role_keys if key not in role_by_key)
    if missing_role_keys:
        raise PortalApiSemanticError(
            ROLE_NOT_REQUESTABLE_MESSAGE,
            {"role_keys": _json_strings(missing_role_keys)},
        )
    return tuple(role_by_key[key] for key in role_keys)


def _permissions_for_keys(
    *,
    app: App,
    permission_keys: tuple[str, ...],
) -> tuple[Permission, ...]:
    permission_by_key = {
        permission.key: permission
        for permission in Permission.objects.filter(app=app, key__in=permission_keys)
    }
    missing_permission_keys = tuple(key for key in permission_keys if key not in permission_by_key)
    if missing_permission_keys:
        raise PortalApiSemanticError(
            PERMISSION_NOT_REQUESTABLE_MESSAGE,
            {"permission_keys": _json_strings(missing_permission_keys)},
        )
    return tuple(permission_by_key[key] for key in permission_keys)


def _semantic_error_details(exc: PortalApiSemanticError | AccessRequestSubmissionError) -> dict[
    str,
    JsonValue,
]:
    match exc:
        case PortalApiSemanticError(details=details):
            return details
        case AccessRequestSubmissionError(messages=messages):
            return {"messages": _json_strings(messages)}


def _json_strings(values: tuple[str, ...]) -> list[JsonValue]:
    result: list[JsonValue] = []
    result.extend(values)
    return result


def _error_response(
    code: ErrorCode,
    message: str,
    details: dict[str, JsonValue] | None = None,
    *,
    status: HTTPStatus,
) -> JsonResponse:
    return _json_response(build_error_response(code, message, details), status=status)


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


def _json_response(
    payload: dict[str, JsonValue] | ErrorResponse,
    *,
    status: HTTPStatus = HTTPStatus.OK,
) -> JsonResponse:
    return JsonResponse(
        payload,
        status=status,
        json_dumps_params={"ensure_ascii": False},
    )
