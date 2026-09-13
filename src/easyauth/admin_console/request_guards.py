from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from easyauth.admin_console.api_responses import error_response
from easyauth.admin_console.identity import actor_from_request
from easyauth.api.errors import ErrorCode
from easyauth.api.responses import require_method

if TYPE_CHECKING:
    from django.http import HttpRequest, JsonResponse

    from easyauth.applications.ownership import ConsoleActor

__all__ = ["require_console_actor", "require_method", "require_post"]


def require_console_actor(request: HttpRequest) -> ConsoleActor | JsonResponse:
    actor = actor_from_request(request)
    if actor is None:
        return error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            "控制台登录已失效。",
            status=HTTPStatus.UNAUTHORIZED,
        )
    return actor


def require_post(request: HttpRequest) -> JsonResponse | None:
    return require_method(request, "POST")
