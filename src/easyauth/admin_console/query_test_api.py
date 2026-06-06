from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.query_tester import (
    PermissionQueryTestResult,
    run_permission_query_test,
)
from easyauth.api.errors import ErrorCode, ErrorResponse, JsonValue, build_error_response
from easyauth.applications.models import App
from easyauth.applications.ownership import ConsoleActor, can_view_app

type ConsoleApiResult = ConsoleActor | JsonResponse
type AppLookupResult = App | JsonResponse


class _PermissionQueryTestPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    user_id: str = Field(min_length=1, max_length=128)
    token: str = Field(min_length=1)


def console_permission_query_test(request: HttpRequest, app_key: str) -> JsonResponse:
    match _actor_from_request(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    match _app_for_actor(actor, app_key):
        case App() as app:
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
        payload = _PermissionQueryTestPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    result = run_permission_query_test(
        app=app,
        user_id=payload.user_id,
        plaintext_token=payload.token,
        actor_id=actor.user_id,
    )
    return _result_response(app=app, user_id=payload.user_id.strip(), result=result)


def _actor_from_request(request: HttpRequest) -> ConsoleApiResult:
    user = request.user
    if not user.is_authenticated:
        return _error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            "控制台登录已失效。",
            status=HTTPStatus.UNAUTHORIZED,
        )
    return ConsoleActor(
        user_id=user.get_username(),
        is_superuser=bool(getattr(user, "is_superuser", False)),
    )


def _app_for_actor(actor: ConsoleActor, app_key: str) -> AppLookupResult:
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return _error_response(
            ErrorCode.NOT_FOUND,
            "应用不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    if not can_view_app(actor, app):
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "无权限访问该应用。",
            status=HTTPStatus.FORBIDDEN,
        )
    return app


def _result_response(
    *,
    app: App,
    user_id: str,
    result: PermissionQueryTestResult,
) -> JsonResponse:
    if result.status_code == HTTPStatus.OK:
        return _json_response(_success_payload(app=app, user_id=user_id, result=result))
    return _error_response(
        _error_code(result),
        result.explanation,
        {
            "app_key": app.app_key,
            "user_id": user_id,
            "status_code": result.status_code,
            "code": result.code,
        },
        status=result.status_code,
    )


def _success_payload(
    *,
    app: App,
    user_id: str,
    result: PermissionQueryTestResult,
) -> dict[str, JsonValue]:
    roles: list[JsonValue] = []
    roles.extend(result.roles)
    permissions: list[JsonValue] = []
    permissions.extend(result.permissions)
    return {
        "app_key": app.app_key,
        "user_id": user_id,
        "allowed": len(result.roles) > 0 or len(result.permissions) > 0,
        "roles": roles,
        "permissions": permissions,
        "version": result.version,
        "expires_at": None if result.expires_at is None else result.expires_at.isoformat(),
        "status_code": result.status_code,
        "code": result.code,
        "explanation": result.explanation,
    }


def _error_code(result: PermissionQueryTestResult) -> ErrorCode:
    match result.code:
        case "validation_error":
            return ErrorCode.VALIDATION_ERROR
        case "authentication_failed":
            return ErrorCode.AUTHENTICATION_FAILED
        case "permission_denied":
            return ErrorCode.PERMISSION_DENIED
        case "internal_permission_query_error":
            return ErrorCode.INTERNAL_ERROR
        case _:
            return ErrorCode.INTERNAL_ERROR


def _error_response(
    code: ErrorCode,
    message: str,
    details: dict[str, JsonValue] | None = None,
    *,
    status: int,
) -> JsonResponse:
    return _json_response(build_error_response(code, message, details), status=status)


def _json_response(
    payload: dict[str, JsonValue] | ErrorResponse,
    *,
    status: int = HTTPStatus.OK,
) -> JsonResponse:
    return JsonResponse(
        payload,
        status=status,
        json_dumps_params={"ensure_ascii": False},
    )
