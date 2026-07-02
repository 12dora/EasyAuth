from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from easyauth.admin_console.api_responses import error_response
from easyauth.admin_console.identity import actor_from_request
from easyauth.api.errors import ErrorCode

if TYPE_CHECKING:
    from django.http import HttpRequest, JsonResponse

    from easyauth.applications.ownership import ConsoleActor


def require_console_actor(request: HttpRequest) -> ConsoleActor | JsonResponse:
    actor = actor_from_request(request)
    if actor is None:
        return error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            "控制台登录已失效。",
            status=HTTPStatus.UNAUTHORIZED,
        )
    if not actor.is_superuser:
        return error_response(
            ErrorCode.PERMISSION_DENIED,
            "无权访问控制台。",
            status=HTTPStatus.FORBIDDEN,
        )
    return actor


def require_post(request: HttpRequest) -> JsonResponse | None:
    if request.method == "POST":
        return None
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        "请求方法无效。",
        status=HTTPStatus.METHOD_NOT_ALLOWED,
    )
