from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar, Final

from django.http import HttpRequest, JsonResponse
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.api_payloads import paginated_list_payload
from easyauth.admin_console.operation_filters import paginate_queryset
from easyauth.admin_console.permission_template_api_data import (
    CachedTemplatePreview,
    load_template_preview,
    preview_changes,
    preview_summary,
    store_template_preview,
    template_version_item,
    template_version_pagination_item,
)
from easyauth.api.errors import ErrorCode, ErrorResponse, JsonValue, build_error_response
from easyauth.applications.models import App, PermissionTemplateVersion
from easyauth.applications.ownership import ConsoleActor, can_manage_app, can_view_app
from easyauth.applications.permission_templates import (
    PermissionTemplateImportError,
    apply_permission_template,
    parse_permission_template,
    parse_template_format,
    preview_permission_template,
)

CONFLICT_TEMPLATE_CODES: Final = frozenset(
    {
        "permission_template_version_duplicate",
        "permission_template_version_not_increasing",
    },
)

type ConsoleApiResult = ConsoleActor | JsonResponse
type AppApiResult = App | JsonResponse


class _TemplatePreviewPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    template_format: str = Field(
        min_length=1,
        max_length=16,
        validation_alias=AliasChoices("template_format", "format"),
    )
    template: str = Field(min_length=1, validation_alias=AliasChoices("template", "content"))


def permission_template_preview_api(request: HttpRequest, app_key: str) -> JsonResponse:
    match _read_context(request, app_key):
        case App() as app:
            pass
        case JsonResponse() as response:
            return response

    if request.method != "POST":
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求方法无效。",
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )
    try:
        payload = _TemplatePreviewPayload.model_validate_json(request.body)
        template_format = parse_template_format(payload.template_format)
        template = parse_permission_template(
            raw_template=payload.template,
            template_format=template_format,
            imported_by=request.user.get_username(),
        )
        preview = preview_permission_template(app=app, template=template)
    except ValidationError as exc:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    except PermissionTemplateImportError as exc:
        return _template_error_response(exc)
    return _json_response(
        {
            "app_key": app.app_key,
            "preview_id": store_template_preview(
                CachedTemplatePreview(
                    app_key=app.app_key,
                    template_format=payload.template_format,
                    template=payload.template,
                ),
            ),
            "summary": preview_summary(template.version, preview.actions),
            "changes": preview_changes(preview.actions),
        },
    )


def permission_template_confirm_api(
    request: HttpRequest,
    app_key: str,
    preview_id: str,
) -> JsonResponse:
    match _write_context(request, app_key):
        case App() as app:
            pass
        case JsonResponse() as response:
            return response

    if request.method != "POST":
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求方法无效。",
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )
    match load_template_preview(preview_id):
        case CachedTemplatePreview(app_key=cached_app_key) as cached if cached_app_key == app_key:
            pass
        case _:
            return _error_response(
                ErrorCode.NOT_FOUND,
                "模板预览不存在或已过期。",
                status=HTTPStatus.NOT_FOUND,
            )
    try:
        template_format = parse_template_format(cached.template_format)
        template = parse_permission_template(
            raw_template=cached.template,
            template_format=template_format,
            imported_by=request.user.get_username(),
        )
        result = apply_permission_template(app=app, template=template)
    except PermissionTemplateImportError as exc:
        return _template_error_response(exc)
    version = template_version_item(result.template_version)
    return _json_response(
        {
            "app_key": app.app_key,
            "template_version": result.template_version.version,
            "status": result.template_version.status,
            "version": version,
            "template_version_detail": version,
            "summary": preview_summary(template.version, result.actions),
            "changes": preview_changes(result.actions),
        },
    )


def permission_template_versions_api(request: HttpRequest, app_key: str) -> JsonResponse:
    match _read_context(request, app_key):
        case App() as app:
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


def _read_context(request: HttpRequest, app_key: str) -> AppApiResult:
    match _actor_from_request(request):
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
    return app


def _write_context(request: HttpRequest, app_key: str) -> AppApiResult:
    match _actor_from_request(request):
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
    return app


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


def _template_error_response(exc: PermissionTemplateImportError) -> JsonResponse:
    status = (
        HTTPStatus.CONFLICT
        if exc.code in CONFLICT_TEMPLATE_CODES
        else HTTPStatus.UNPROCESSABLE_ENTITY
    )
    error_code = (
        ErrorCode.CONFLICT
        if status == HTTPStatus.CONFLICT
        else ErrorCode.SEMANTIC_VALIDATION_ERROR
    )
    return _error_response(
        error_code,
        exc.message,
        {"code": exc.code, "subject": exc.subject},
        status=status,
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
