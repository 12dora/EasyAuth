from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from easyauth.applications.permission_templates import (
    PermissionTemplateImportError,
    PermissionTemplateInput,
    TemplateAction,
    apply_permission_template,
    parse_permission_template,
    parse_template_format,
    preview_permission_template,
)

if TYPE_CHECKING:
    from easyauth.applications.models import App

type PermissionTemplateConsoleState = Literal["preview", "applied", "error"]


@dataclass(frozen=True, slots=True)
class PermissionTemplateConsoleResult:
    state: PermissionTemplateConsoleState
    message: str
    template_format: str
    raw_template: str
    actions: tuple[TemplateAction, ...] = ()
    error_code: str = ""
    error_subject: str = ""


def handle_permission_template_post(
    *,
    app: App,
    action: str,
    raw_template: str,
    raw_format: str,
    actor_id: str,
) -> PermissionTemplateConsoleResult:
    try:
        template_format = parse_template_format(raw_format)
        template = parse_permission_template(
            raw_template=raw_template,
            template_format=template_format,
            imported_by=actor_id,
        )
        match action:
            case "preview_permission_template":
                return _preview_template_result(app, template, template_format, raw_template)
            case "apply_permission_template":
                return _apply_template_result(app, template, template_format, raw_template)
            case _:
                return _unknown_template_action_result(
                    action=action,
                    raw_format=raw_format,
                    raw_template=raw_template,
                )
    except PermissionTemplateImportError as exc:
        return PermissionTemplateConsoleResult(
            state="error",
            message=exc.message,
            template_format=raw_format,
            raw_template=raw_template,
            error_code=exc.code,
            error_subject=exc.subject,
        )


def _preview_template_result(
    app: App,
    template: PermissionTemplateInput,
    template_format: str,
    raw_template: str,
) -> PermissionTemplateConsoleResult:
    preview = preview_permission_template(app=app, template=template)
    return PermissionTemplateConsoleResult(
        state="preview",
        message="模板预览完成, 请确认差异后导入。",
        template_format=template_format,
        raw_template=raw_template,
        actions=preview.actions,
    )


def _apply_template_result(
    app: App,
    template: PermissionTemplateInput,
    template_format: str,
    raw_template: str,
) -> PermissionTemplateConsoleResult:
    result = apply_permission_template(app=app, template=template)
    return PermissionTemplateConsoleResult(
        state="applied",
        message="模板已导入。",
        template_format=template_format,
        raw_template=raw_template,
        actions=result.actions,
    )


def _unknown_template_action_result(
    *,
    action: str,
    raw_format: str,
    raw_template: str,
) -> PermissionTemplateConsoleResult:
    return PermissionTemplateConsoleResult(
        state="error",
        message="未知模板操作。",
        template_format=raw_format,
        raw_template=raw_template,
        error_code="permission_template_action_invalid",
        error_subject=action,
    )
