from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from pydantic import ValidationError

from easyauth.admin_console.configuration import (
    ConsoleMutationActor,
    RolePermissionMutation,
    set_role_permission,
)
from easyauth.admin_console.permission_catalog_data import (
    catalog_version,
    matrix_objects,
    matrix_objects_by_key,
    matrix_payload,
    permission_groups_payload,
    permission_tree_payload,
    permissions_payload,
    roles_payload,
)
from easyauth.admin_console.permission_matrix_payloads import MatrixSavePayload
from easyauth.api.errors import ErrorCode, ErrorResponse, JsonValue, build_error_response
from easyauth.applications.models import App, Permission, Role
from easyauth.applications.ownership import ConsoleActor, can_manage_app, can_view_app

type ConsoleApiResult = ConsoleActor | JsonResponse
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

    with transaction.atomic():
        locked_app = App.objects.select_for_update().get(id=app.id)
        current_version = catalog_version(locked_app)
        match _matrix_base_version(payload):
            case str() as base_version:
                pass
            case JsonResponse() as response:
                return response
        if base_version != current_version:
            return _error_response(
                ErrorCode.CONFLICT,
                "权限矩阵已被更新, 请刷新后重试。",
                {"current_version": current_version},
                status=HTTPStatus.CONFLICT,
            )
        match _matrix_mutations(locked_app, payload):
            case list() as mutations:
                pass
            case JsonResponse() as response:
                return response
        for role, permission, enabled in mutations:
            set_role_permission(
                RolePermissionMutation(
                    app=locked_app,
                    role=role,
                    permission=permission,
                    enabled=enabled,
                    actor=ConsoleMutationActor(actor_id=actor.user_id),
                ),
            )
    return _json_response(matrix_payload(app))


def _matrix_mutations(
    app: App,
    payload: MatrixSavePayload,
) -> list[tuple[Role, Permission, bool]] | JsonResponse:
    mutations: list[tuple[Role, Permission, bool]] = []
    for assignment in payload.assignments:
        match matrix_objects(
            app,
            role_id=assignment.role_id,
            permission_id=assignment.permission_id,
        ):
            case role, permission:
                mutations.append((role, permission, assignment.enabled))
            case None:
                return _error_response(
                    ErrorCode.VALIDATION_ERROR,
                    "角色或权限不属于当前 App。",
                    status=HTTPStatus.BAD_REQUEST,
                )
    for assignment in payload.add:
        match matrix_objects_by_key(
            app,
            role_key=assignment.role_key,
            permission_key=assignment.permission_key,
        ):
            case role, permission:
                mutations.append((role, permission, True))
            case None:
                return _error_response(
                    ErrorCode.VALIDATION_ERROR,
                    "角色或权限不属于当前 App。",
                    status=HTTPStatus.BAD_REQUEST,
                )
    for assignment in payload.remove:
        match matrix_objects_by_key(
            app,
            role_key=assignment.role_key,
            permission_key=assignment.permission_key,
        ):
            case role, permission:
                mutations.append((role, permission, False))
            case None:
                return _error_response(
                    ErrorCode.VALIDATION_ERROR,
                    "角色或权限不属于当前 App。",
                    status=HTTPStatus.BAD_REQUEST,
                )
    return mutations


def _matrix_base_version(payload: MatrixSavePayload) -> str | JsonResponse:
    if payload.base_version is not None:
        return payload.base_version
    if payload.version is not None:
        return payload.version
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        "矩阵提交参数无效。",
        status=HTTPStatus.BAD_REQUEST,
    )


def _read_context(request: HttpRequest, app_key: str) -> AppApiResult:
    match _actor_from_request(request):
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
    match _actor_from_request(request):
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


def _actor_from_request(request: HttpRequest) -> ConsoleApiResult:
    user = request.user
    if not user.is_authenticated:
        return _error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            "控制台登录已失效。",
            status=HTTPStatus.UNAUTHORIZED,
        )
    return ConsoleActor(
        user_id=user.get_username(),
        is_superuser=bool(getattr(user, "is_superuser", False)),
    )


def _error_response(
    code: ErrorCode,
    message: str,
    details: dict[str, JsonValue] | None = None,
    *,
    status: HTTPStatus,
) -> JsonResponse:
    return _json_response(build_error_response(code, message, details), status=status)


def _json_response(
    payload: dict[str, JsonValue] | ErrorResponse,
    *,
    status: HTTPStatus = HTTPStatus.OK,
) -> JsonResponse:
    return JsonResponse(payload, status=status, json_dumps_params={"ensure_ascii": False})
