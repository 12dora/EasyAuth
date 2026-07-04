from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from easyauth.api.errors import ErrorCode
from easyauth.api.responses import error_response, json_response

if TYPE_CHECKING:
    from django.http import JsonResponse

__all__ = ["error_response", "json_response", "method_not_allowed_response"]


def method_not_allowed_response() -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        "不支持的请求方法。",
        status=HTTPStatus.METHOD_NOT_ALLOWED,
    )
