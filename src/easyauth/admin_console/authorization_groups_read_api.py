from __future__ import annotations

from http import HTTPStatus

from django.http import HttpRequest, JsonResponse

from easyauth.admin_console.authorization_groups_payloads import AuthorizationGroupQueryOptions
from easyauth.admin_console.catalog_write_common import error_response, json_response
from easyauth.admin_console.operation_filters import (
    OperationFilterValidationError,
    operation_filter_error_response,
    paginate_queryset,
)
from easyauth.admin_console.permission_catalog_data import (
    active_authorization_groups_queryset,
    authorization_groups_page_payload,
)
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode
from easyauth.api.pagination import pagination_item
from easyauth.applications.models import App
from easyauth.applications.ownership import ConsoleActor, can_view_app


def read_authorization_groups(request: HttpRequest, app_key: str) -> JsonResponse:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return error_response(ErrorCode.NOT_FOUND, "App 不存在。", status=HTTPStatus.NOT_FOUND)
    if not can_view_app(actor, app):
        return error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有 active App owner/developer 可以访问该 App 权限目录。",
            status=HTTPStatus.FORBIDDEN,
        )
    match _authorization_group_query_options(request):
        case AuthorizationGroupQueryOptions() as options:
            try:
                page = paginate_queryset(
                    active_authorization_groups_queryset(
                        app,
                        include_inactive=options.include_inactive,
                        status=options.status,
                    ),
                    request.GET,
                )
            except OperationFilterValidationError as exc:
                return operation_filter_error_response(exc)
            return json_response(
                authorization_groups_page_payload(
                    app,
                    groups=page.items,
                    pagination=pagination_item(page),
                )
            )
        case JsonResponse() as response:
            return response


def _authorization_group_query_options(
    request: HttpRequest,
) -> AuthorizationGroupQueryOptions | JsonResponse:
    status = request.GET.get("status", "").strip()
    if status not in {"", "active", "inactive"}:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "status 必须为 active 或 inactive。",
            {"status": status},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    include_inactive_value = request.GET.get("include_inactive", "").strip()
    match include_inactive_value:
        case "" | "false":
            include_inactive = False
        case "true":
            include_inactive = True
        case _:
            return error_response(
                ErrorCode.VALIDATION_ERROR,
                "include_inactive 必须为 true 或 false。",
                {"include_inactive": include_inactive_value},
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
    return AuthorizationGroupQueryOptions(include_inactive=include_inactive, status=status)
