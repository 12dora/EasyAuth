from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from django.http import HttpRequest, JsonResponse

from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.permission_catalog_data import (
    permission_groups_payload,
    permission_tree_payload,
    permissions_payload,
)
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App
from easyauth.applications.ownership import ConsoleActor, can_view_app

if TYPE_CHECKING:
    from collections.abc import Callable

type AppApiResult = App | JsonResponse


def console_permission_tree(request: HttpRequest, app_key: str) -> JsonResponse:
    match _read_context(request, app_key):
        case App() as app:
            return _json_response(permission_tree_payload(app))
        case JsonResponse() as response:
            return response


def read_context_response(
    request: HttpRequest,
    app_key: str,
    payload_func: Callable[[App], dict[str, JsonValue]],
) -> JsonResponse:
    match _read_context(request, app_key):
        case App() as app:
            return _json_response(payload_func(app))
        case JsonResponse() as response:
            return response


def console_permission_groups(request: HttpRequest, app_key: str) -> JsonResponse:
    match _read_context(request, app_key):
        case App() as app:
            return _json_response(permission_groups_payload(app))
        case JsonResponse() as response:
            return response


def console_permissions(request: HttpRequest, app_key: str) -> JsonResponse:
    match _read_context(request, app_key):
        case App() as app:
            return _json_response(permissions_payload(app))
        case JsonResponse() as response:
            return response


def _read_context(request: HttpRequest, app_key: str) -> AppApiResult:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return _error_response(
            ErrorCode.NOT_FOUND,
            "App 不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    if not can_view_app(actor, app):
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有 active App owner/developer 可以访问该 App 权限目录。",
            status=HTTPStatus.FORBIDDEN,
        )
    return app
