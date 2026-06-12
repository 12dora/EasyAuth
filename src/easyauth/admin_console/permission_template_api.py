from __future__ import annotations

from http import HTTPStatus

from django.http import HttpRequest, JsonResponse

from easyauth.admin_console.api_payloads import paginated_list_payload
from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.operation_filters import paginate_queryset
from easyauth.admin_console.permission_template_api_data import (
    template_version_item,
    template_version_pagination_item,
)
from easyauth.admin_console.permission_template_handlers import (
    TemplateHandlerError,
    confirm_template_import,
    preview_template_import,
)
from easyauth.admin_console.request_guards import require_console_actor, require_post
from easyauth.api.errors import ErrorCode
from easyauth.applications.models import App, PermissionTemplateVersion
from easyauth.applications.ownership import ConsoleActor, can_manage_app, can_view_app

type AppActorApiResult = tuple[App, ConsoleActor] | JsonResponse


def permission_template_preview_api(request: HttpRequest, app_key: str) -> JsonResponse:
    match _read_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response

    if response := require_post(request):
        return response
    try:
        payload = preview_template_import(app, request.body, actor.user_id)
    except TemplateHandlerError as error:
        return _template_error_response(error)
    return _json_response(payload)


def permission_template_confirm_api(
    request: HttpRequest,
    app_key: str,
    preview_id: str,
) -> JsonResponse:
    match _write_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response

    if response := require_post(request):
        return response
    try:
        payload = confirm_template_import(app, preview_id, actor.user_id)
    except TemplateHandlerError as error:
        return _template_error_response(error)
    return _json_response(payload)


def permission_template_versions_api(request: HttpRequest, app_key: str) -> JsonResponse:
    match _read_context(request, app_key):
        case (App() as app, ConsoleActor()):
            pass
        case JsonResponse() as response:
            return response

    if request.method != "GET":
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求方法无效。",
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )
    page = paginate_queryset(
        PermissionTemplateVersion.objects.filter(app=app).order_by("-version"),
        request.GET,
    )
    latest = PermissionTemplateVersion.objects.filter(app=app).order_by("-version").first()
    items = [template_version_item(template_version) for template_version in page.items]
    return _json_response(
        {
            "app_key": app.app_key,
            "latest_version": latest.version if latest is not None else None,
            **paginated_list_payload(
                items=items,
                pagination=template_version_pagination_item(page),
            ),
        },
    )


def _read_context(request: HttpRequest, app_key: str) -> AppActorApiResult:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response
    app = App.objects.filter(app_key=app_key).first()
    if app is None or not can_view_app(actor, app):
        return _error_response(
            ErrorCode.NOT_FOUND,
            "应用不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    return app, actor


def _write_context(request: HttpRequest, app_key: str) -> AppActorApiResult:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response
    app = App.objects.filter(app_key=app_key).first()
    if app is None or not can_view_app(actor, app):
        return _error_response(
            ErrorCode.NOT_FOUND,
            "应用不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    if not can_manage_app(actor, app):
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有 active App owner 可以确认导入权限模板。",
            status=HTTPStatus.FORBIDDEN,
        )
    return app, actor


def _template_error_response(error: TemplateHandlerError) -> JsonResponse:
    return _error_response(
        error.error_code,
        error.message,
        error.details,
        status=error.status,
    )
