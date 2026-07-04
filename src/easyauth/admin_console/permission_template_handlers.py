from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final, final, override

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.permission_template_api_data import (
    CachedTemplatePreview,
    load_template_preview,
    preview_changes,
    preview_summary,
    store_template_preview,
    template_version_item,
)
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.permission_templates import (
    PermissionTemplateImportError,
    apply_permission_template,
    parse_permission_template,
    parse_template_format,
    preview_permission_template,
)

if TYPE_CHECKING:
    from easyauth.applications.models import App

CONFLICT_TEMPLATE_CODES: Final = frozenset(
    {
        "permission_template_version_duplicate",
        "permission_template_version_not_increasing",
    },
)


@final
class TemplateHandlerError(Exception):
    def __init__(
        self,
        error_code: ErrorCode,
        message: str,
        details: dict[str, JsonValue] | None,
        status: HTTPStatus,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details
        self.status = status

    @override
    def __str__(self) -> str:
        return self.message


class _TemplatePreviewPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    template_format: str = Field(min_length=1, max_length=16)
    template: str = Field(min_length=1)


def preview_template_import(app: App, body: bytes, imported_by: str) -> dict[str, JsonValue]:
    try:
        payload = _TemplatePreviewPayload.model_validate_json(body)
        template_format = parse_template_format(payload.template_format)
        template = parse_permission_template(
            app_key=app.app_key,
            raw_template=payload.template,
            template_format=template_format,
            imported_by=imported_by,
        )
        preview = preview_permission_template(app=app, template=template)
    except ValidationError as exc:
        raise TemplateHandlerError(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            {"errors": str(exc)},
            HTTPStatus.UNPROCESSABLE_ENTITY,
        ) from exc
    except PermissionTemplateImportError as exc:
        raise _template_error(exc) from exc
    return {
        "app_key": app.app_key,
        "preview_id": store_template_preview(
            CachedTemplatePreview(
                app_key=app.app_key,
                template_format=payload.template_format,
                template=payload.template,
            ),
        ),
        "summary": preview_summary(template.schema_version, preview.actions),
        "changes": preview_changes(preview.actions),
    }


def confirm_template_import(app: App, preview_id: str, imported_by: str) -> dict[str, JsonValue]:
    match load_template_preview(preview_id):
        case (
            CachedTemplatePreview(app_key=cached_app_key) as cached
        ) if cached_app_key == app.app_key:
            pass
        case _:
            raise TemplateHandlerError(
                ErrorCode.NOT_FOUND,
                "模板预览不存在或已过期。",
                None,
                HTTPStatus.NOT_FOUND,
            )
    try:
        template_format = parse_template_format(cached.template_format)
        template = parse_permission_template(
            app_key=app.app_key,
            raw_template=cached.template,
            template_format=template_format,
            imported_by=imported_by,
        )
        result = apply_permission_template(app=app, template=template)
    except PermissionTemplateImportError as exc:
        raise _template_error(exc) from exc
    version = template_version_item(result.template_version)
    return {
        "app_key": app.app_key,
        "catalog_version": app.catalog_version,
        "template_version": result.template_version.version,
        "status": result.template_version.status,
        "template_version_detail": version,
        "summary": preview_summary(template.schema_version, result.actions),
        "changes": preview_changes(result.actions),
    }


def _template_error(exc: PermissionTemplateImportError) -> TemplateHandlerError:
    status = (
        HTTPStatus.CONFLICT
        if exc.code in CONFLICT_TEMPLATE_CODES
        else HTTPStatus.UNPROCESSABLE_ENTITY
    )
    error_code = (
        ErrorCode.CONFLICT if status == HTTPStatus.CONFLICT else ErrorCode.SEMANTIC_VALIDATION_ERROR
    )
    return TemplateHandlerError(
        error_code,
        exc.message,
        {"code": exc.code, "subject": exc.subject},
        status,
    )
