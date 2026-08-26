"""记录模板版本、导入审计、catalog_version 递增, 以及导出当前 manifest。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.applications.catalog_version import bump_catalog_version
from easyauth.applications.manifest_hashing import canonical_manifest_hash_from_template
from easyauth.applications.models import App, PermissionTemplateVersion
from easyauth.applications.ops_models import TEMPLATE_STATUS_IMPORTED
from easyauth.applications.permission_template_exporting import (
    export_app,
    export_approval_rules,
    export_authorization_groups,
    export_permission_groups,
    export_permissions,
    export_scopes,
    latest_manifest_schema_version,
)
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from easyauth.applications.models import JsonValue
    from easyauth.applications.permission_template_types import AppManifestInput, TemplateAction

PERMISSION_TEMPLATE_IMPORTED_EVENT = "app_manifest_imported"


def record_template_version(
    app: App,
    template: AppManifestInput,
    actions: tuple[TemplateAction, ...],
) -> PermissionTemplateVersion:
    template_version = PermissionTemplateVersion(
        app=app,
        version=template.schema_version,
        source=template.source,
        content_hash=canonical_manifest_hash_from_template(template.raw_template),
        raw_template=template.raw_template,
        import_summary={
            "manifest_schema_version": template.schema_version,
            "actions": [action.action for action in actions],
        },
        imported_by=template.imported_by,
        status=TEMPLATE_STATUS_IMPORTED,
    )
    template_version.full_clean()
    template_version.save()
    return template_version


def record_import_event(
    app: App,
    template: AppManifestInput,
    template_version: PermissionTemplateVersion,
    actions: tuple[TemplateAction, ...],
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=template.imported_by,
            action=PERMISSION_TEMPLATE_IMPORTED_EVENT,
            target_type="permission_template_version",
            target_id=str(template_version.id),
            metadata={
                "app_key": app.app_key,
                "version": template.schema_version,
                "action_count": len(actions),
            },
        ),
    )


def bump_manifest_catalog_version(
    app: App,
    template: AppManifestInput,
    actions: tuple[TemplateAction, ...],
) -> None:
    _ = bump_catalog_version(
        app,
        actor_id=template.imported_by,
        reason="app_manifest_imported",
        metadata={"action_count": len(actions), "schema_version": template.schema_version},
    )


def export_manifest(app: App) -> dict[str, JsonValue]:
    return {
        "schema_version": latest_manifest_schema_version(app),
        "app": export_app(app),
        "scopes": export_scopes(app),
        "permission_groups": export_permission_groups(app),
        "permissions": export_permissions(app),
        "authorization_groups": export_authorization_groups(app),
        "approval_rules": export_approval_rules(app),
    }
