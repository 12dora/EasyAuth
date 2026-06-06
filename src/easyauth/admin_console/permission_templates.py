from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from easyauth.applications.permission_templates import (
    PermissionTemplateImportError,
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
                preview = preview_permission_template(app=app, template=template)
                return PermissionTemplateConsoleResult(
                    state="preview",
                    message="模板预览完成, 请确认差异后导入。",
                    template_format=template_format,
                    raw_template=raw_template,
                    actions=preview.actions,
                )
            case "apply_permission_template":
                result = apply_permission_template(app=app, template=template)
                return PermissionTemplateConsoleResult(
                    state="applied",
                    message="模板已导入。",
                    template_format=template_format,
                    raw_template=raw_template,
                    actions=result.actions,
                )
            case _:
                return PermissionTemplateConsoleResult(
                    state="error",
                    message="未知模板操作。",
                    template_format=raw_format,
                    raw_template=raw_template,
                    error_code="permission_template_action_invalid",
                    error_subject=action,
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
