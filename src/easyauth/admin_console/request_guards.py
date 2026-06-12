from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from easyauth.admin_console.api_responses import error_response
from easyauth.api.errors import ErrorCode
from easyauth.applications.ownership import ConsoleActor

if TYPE_CHECKING:
    from django.http import HttpRequest, JsonResponse


def require_console_actor(request: HttpRequest) -> ConsoleActor | JsonResponse:
    user = request.user
    if not user.is_authenticated:
        return error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            "控制台登录已失效。",
            status=HTTPStatus.UNAUTHORIZED,
        )
    return ConsoleActor(
        user_id=user.get_username(),
        is_superuser=bool(getattr(user, "is_superuser", False)),
    )


def require_post(request: HttpRequest) -> JsonResponse | None:
    if request.method == "POST":
        return None
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        "请求方法无效。",
        status=HTTPStatus.METHOD_NOT_ALLOWED,
    )
