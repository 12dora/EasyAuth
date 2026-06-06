from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

from easyauth.applications.models import PermissionTemplateVersion
from easyauth.applications.permission_template_flattening import flatten_template
from easyauth.applications.permission_template_parsing import (
    TemplateFormat,
    parse_permission_template,
    parse_template_format,
)
from easyauth.applications.permission_template_storage import (
    record_import_event,
    record_template_version,
    template_actions,
    upsert_groups,
    upsert_permissions,
)
from easyauth.applications.permission_template_types import (
    PermissionTemplateImportError,
    PermissionTemplateImportResult,
    PermissionTemplateInput,
    PermissionTemplatePreview,
    TemplateAction,
    TemplateNodeInput,
)

if TYPE_CHECKING:
    from easyauth.applications.models import App

__all__ = [
    "PermissionTemplateImportError",
    "PermissionTemplateImportResult",
    "PermissionTemplateInput",
    "PermissionTemplatePreview",
    "TemplateAction",
    "TemplateFormat",
    "TemplateNodeInput",
    "apply_permission_template",
    "parse_permission_template",
    "parse_template_format",
    "preview_permission_template",
]


def preview_permission_template(
    *,
    app: App,
    template: PermissionTemplateInput,
) -> PermissionTemplatePreview:
    flattened = flatten_template(template)
    return PermissionTemplatePreview(actions=template_actions(app, flattened))


@transaction.atomic
def apply_permission_template(
    *,
    app: App,
    template: PermissionTemplateInput,
) -> PermissionTemplateImportResult:
    _reject_duplicate_template_version(app=app, version=template.version)
    flattened = flatten_template(template)
    actions = template_actions(app, flattened)
    group_by_key = upsert_groups(app, flattened.groups)
    upsert_permissions(app, flattened.permissions, group_by_key)
    template_version = record_template_version(app, template, actions)
    record_import_event(app, template, template_version, actions)
    return PermissionTemplateImportResult(template_version=template_version, actions=actions)


def _reject_duplicate_template_version(*, app: App, version: int) -> None:
    latest_template = (
        PermissionTemplateVersion.objects.filter(app=app).order_by("-version").first()
    )
    if latest_template is None or version > latest_template.version:
        return
    if version < latest_template.version:
        raise PermissionTemplateImportError(
            code="permission_template_version_not_increasing",
            message="权限模板版本必须大于当前最新版本。",
            subject=f"{version}<={latest_template.version}",
        )
    raise PermissionTemplateImportError(
        code="permission_template_version_duplicate",
        message="权限模板版本已存在。",
        subject=str(version),
    )
