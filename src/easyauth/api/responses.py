from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from django.http import JsonResponse

from easyauth.api.errors import ErrorCode, ErrorResponse, JsonValue, build_error_response

if TYPE_CHECKING:
    from django.http import HttpRequest

METHOD_NOT_ALLOWED_MESSAGE = "不支持的请求方法。"
REQUIRE_METHOD_EMPTY_MESSAGE = "require_method 至少需要一个 HTTP 方法。"


def error_response(
    code: ErrorCode,
    message: str,
    details: dict[str, JsonValue] | None = None,
    *,
    status: int | HTTPStatus,
) -> JsonResponse:
    return json_response(build_error_response(code, message, details), status=status)


def json_response(
    payload: dict[str, JsonValue] | ErrorResponse,
    *,
    status: int | HTTPStatus = HTTPStatus.OK,
) -> JsonResponse:
    return JsonResponse(
        payload,
        status=status,
        json_dumps_params={"ensure_ascii": False},
    )


def method_not_allowed_response() -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        METHOD_NOT_ALLOWED_MESSAGE,
        status=HTTPStatus.METHOD_NOT_ALLOWED,
    )


def require_method(request: HttpRequest, *methods: str) -> JsonResponse | None:
    if not methods:
        raise ValueError(REQUIRE_METHOD_EMPTY_MESSAGE)
    if request.method in methods:
        return None
    return method_not_allowed_response()
