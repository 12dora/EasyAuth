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
    bump_manifest_catalog_version,
    export_manifest,
    record_import_event,
    record_template_version,
    template_actions,
    upsert_manifest,
)
from easyauth.applications.permission_template_types import (
    AppManifestInput,
    PermissionTemplateImportError,
    PermissionTemplateImportResult,
    PermissionTemplateInput,
    PermissionTemplatePreview,
    TemplateAction,
)

if TYPE_CHECKING:
    from easyauth.applications.models import App

__all__ = [
    "AppManifestInput",
    "PermissionTemplateImportError",
    "PermissionTemplateImportResult",
    "PermissionTemplateInput",
    "PermissionTemplatePreview",
    "TemplateAction",
    "TemplateFormat",
    "apply_permission_template",
    "export_manifest",
    "parse_permission_template",
    "parse_template_format",
    "preview_permission_template",
]


def preview_permission_template(
    *,
    app: App,
    template: AppManifestInput,
) -> PermissionTemplatePreview:
    flattened = flatten_template(template)
    return PermissionTemplatePreview(actions=template_actions(app, flattened))


@transaction.atomic
def apply_permission_template(
    *,
    app: App,
    template: AppManifestInput,
) -> PermissionTemplateImportResult:
    _reject_duplicate_template_version(app=app, version=template.schema_version)
    flattened = flatten_template(template)
    actions = template_actions(app, flattened)
    upsert_manifest(app, template)
    template_version = record_template_version(app, template, actions)
    record_import_event(app, template, template_version, actions)
    bump_manifest_catalog_version(app, template, actions)
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
            message="App manifest 版本必须大于当前最新版本。",
            subject=f"{version}<={latest_template.version}",
        )
    raise PermissionTemplateImportError(
        code="permission_template_version_duplicate",
        message="App manifest 版本已存在。",
        subject=str(version),
    )
