from __future__ import annotations

from http import HTTPStatus

from django.http import JsonResponse

from easyauth.api.errors import ErrorCode, ErrorResponse, JsonValue, build_error_response


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
