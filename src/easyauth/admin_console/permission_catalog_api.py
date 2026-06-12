from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus

from django.http import HttpRequest, JsonResponse
from pydantic import ValidationError

from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.permission_catalog_data import (
    catalog_version,
    matrix_payload,
    permission_groups_payload,
    permission_tree_payload,
    permissions_payload,
    roles_payload,
)
from easyauth.admin_console.permission_catalog_handlers import (
    MatrixSaveConflictError,
    MatrixSaveValidationError,
    save_permission_matrix,
)
from easyauth.admin_console.permission_matrix_payloads import MatrixSavePayload
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode
from easyauth.applications.models import App
from easyauth.applications.ownership import ConsoleActor, can_manage_app, can_view_app

type AppApiResult = App | JsonResponse
type MatrixWriteContextResult = MatrixWriteContext | JsonResponse


@dataclass(frozen=True, slots=True)
class MatrixWriteContext:
    app: App
    actor: ConsoleActor


def console_permission_tree(request: HttpRequest, app_key: str) -> JsonResponse:
    match _read_context(request, app_key):
        case App() as app:
            return _json_response(permission_tree_payload(app))
        case JsonResponse() as response:
            return response


def console_permission_groups(request: HttpRequest, app_key: str) -> JsonResponse:
    match _read_context(request, app_key):
        case App() as app:
            return _json_response(permission_groups_payload(app))
        case JsonResponse() as response:
            return response


def console_roles(request: HttpRequest, app_key: str) -> JsonResponse:
    match _read_context(request, app_key):
        case App() as app:
            return _json_response(roles_payload(app))
        case JsonResponse() as response:
            return response


def console_permissions(request: HttpRequest, app_key: str) -> JsonResponse:
    match _read_context(request, app_key):
        case App() as app:
            return _json_response(permissions_payload(app))
        case JsonResponse() as response:
            return response


def console_role_permission_matrix(request: HttpRequest, app_key: str) -> JsonResponse:
    match _read_context(request, app_key):
        case App() as app:
            pass
        case JsonResponse() as response:
            return response

    if request.method == "GET":
        return _json_response(matrix_payload(app))
    if request.method in {"POST", "PATCH"}:
        match _write_context(request, app_key):
            case MatrixWriteContext(app=write_app, actor=actor):
                return _save_matrix(request, write_app, actor)
            case JsonResponse() as response:
                return response
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        "不支持的请求方法。",
        status=HTTPStatus.METHOD_NOT_ALLOWED,
    )


def _save_matrix(request: HttpRequest, app: App, actor: ConsoleActor) -> JsonResponse:
    try:
        payload = MatrixSavePayload.model_validate_json(request.body)
    except ValidationError as error:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "矩阵提交参数无效。",
            {"errors": str(error)},
            status=HTTPStatus.BAD_REQUEST,
        )
    try:
        save_permission_matrix(app, payload, actor.user_id, catalog_version)
    except MatrixSaveConflictError as error:
        return _error_response(
            ErrorCode.CONFLICT,
            "权限矩阵已被更新, 请刷新后重试。",
            {"current_version": error.current_version},
            status=HTTPStatus.CONFLICT,
        )
    except MatrixSaveValidationError as error:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            status=HTTPStatus.BAD_REQUEST,
        )
    return _json_response(matrix_payload(app))


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


def _write_context(request: HttpRequest, app_key: str) -> MatrixWriteContextResult:
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
    if not can_manage_app(actor, app):
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有 active App owner 可以保存该 App 权限矩阵。",
            status=HTTPStatus.FORBIDDEN,
        )
    return MatrixWriteContext(app=app, actor=actor)
