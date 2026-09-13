from __future__ import annotations

from http import HTTPStatus
from typing import Final

from django.http import HttpRequest, JsonResponse

from easyauth.admin_console.api_payloads import paginated_list_payload
from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.api_responses import method_not_allowed_response
from easyauth.admin_console.operation_filters import (
    OperationFilterValidationError,
    operation_filter_error_response,
    paginate_queryset,
)
from easyauth.admin_console.permission_template_api_data import (
    template_version_item,
)
from easyauth.admin_console.permission_template_handlers import (
    TemplateHandlerError,
    confirm_template_import,
    preview_template_import,
)
from easyauth.admin_console.request_guards import require_console_actor, require_post
from easyauth.api.errors import ErrorCode
from easyauth.api.ordering import apply_ordering
from easyauth.api.pagination import pagination_item
from easyauth.applications.models import App, PermissionTemplateVersion
from easyauth.applications.ownership import ConsoleActor, can_manage_app, can_view_app
from easyauth.applications.permission_templates import export_manifest

type AppActorApiResult = tuple[App, ConsoleActor] | JsonResponse

TEMPLATE_VERSION_ORDERING: Final[dict[str, str]] = {
    "imported_by": "imported_by",
    "version": "version",
    "imported_at": "imported_at",
}
TEMPLATE_VERSION_DEFAULT_ORDER: Final[tuple[str, ...]] = ("-version",)


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
        return method_not_allowed_response()
    queryset = apply_ordering(
        request,
        PermissionTemplateVersion.objects.filter(app=app),
        TEMPLATE_VERSION_ORDERING,
        TEMPLATE_VERSION_DEFAULT_ORDER,
    )
    if isinstance(queryset, JsonResponse):
        return queryset
    try:
        page = paginate_queryset(
            queryset,
            request.GET,
        )
    except OperationFilterValidationError as exc:
        return operation_filter_error_response(exc)
    latest = PermissionTemplateVersion.objects.filter(app=app).order_by("-version").first()
    items = [template_version_item(template_version) for template_version in page.items]
    return _json_response(
        {
            "app_key": app.app_key,
            "latest_version": latest.version if latest is not None else None,
            **paginated_list_payload(
                items=items,
                pagination=pagination_item(page),
            ),
        },
    )


def app_manifest_api(request: HttpRequest, app_key: str) -> JsonResponse:
    match _read_context(request, app_key):
        case (App() as app, ConsoleActor()):
            pass
        case JsonResponse() as response:
            return response

    if request.method != "GET":
        return method_not_allowed_response()
    return _json_response(export_manifest(app))


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
