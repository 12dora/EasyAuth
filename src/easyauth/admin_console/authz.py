from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from easyauth.admin_console.api_responses import error_response
from easyauth.admin_console.identity import actor_from_request
from easyauth.api.errors import ErrorCode

if TYPE_CHECKING:
    from django.http import HttpRequest, JsonResponse


def require_superuser(request: HttpRequest) -> str | JsonResponse:
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
            "只有系统管理员可以执行该操作。",
            status=HTTPStatus.FORBIDDEN,
        )
    return actor.user_id
