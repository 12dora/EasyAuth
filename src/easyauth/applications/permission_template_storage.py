from __future__ import annotations

from hashlib import sha256

from django.utils import timezone

from easyauth.applications.models import App, Permission, PermissionGroup, PermissionTemplateVersion
from easyauth.applications.ops_models import TEMPLATE_STATUS_IMPORTED
from easyauth.applications.permission_template_types import (
    FlattenedTemplate,
    GroupSpec,
    PermissionSpec,
    PermissionTemplateInput,
    TemplateAction,
)
from easyauth.audit.services import AuditRecord, AuditService

PERMISSION_TEMPLATE_IMPORTED_EVENT = "permission_template_imported"


def template_actions(app: App, flattened: FlattenedTemplate) -> tuple[TemplateAction, ...]:
    actions: list[TemplateAction] = []
    existing_groups = {group.key: group for group in PermissionGroup.objects.filter(app=app)}
    existing_permissions = {
        permission.key: permission for permission in Permission.objects.filter(app=app)
    }
    for group in flattened.groups:
        existing_group = existing_groups.get(group.key)
        if existing_group is None:
            actions.append(TemplateAction("create_group", group.key, group.parent_key))
        elif existing_group.name != group.name or _parent_key(existing_group) != group.parent_key:
            actions.append(TemplateAction("update_group", group.key, group.parent_key))
    for permission in flattened.permissions:
        existing_permission = existing_permissions.get(permission.key)
        if existing_permission is None:
            actions.append(
                TemplateAction("create_permission", permission.key, permission.group_key),
            )
        elif _permission_group_key(existing_permission) != permission.group_key:
            actions.append(TemplateAction("move_permission", permission.key, permission.group_key))
        elif existing_permission.name != permission.name or not existing_permission.is_active:
            actions.append(
                TemplateAction("update_permission", permission.key, permission.group_key),
            )
    incoming_permission_keys = {permission.key for permission in flattened.permissions}
    actions.extend(
        TemplateAction("deprecate_permission", permission.key)
        for permission in Permission.objects.filter(app=app, is_active=True).order_by("key")
        if permission.key not in incoming_permission_keys
    )
    return tuple(actions)


def upsert_groups(app: App, groups: tuple[GroupSpec, ...]) -> dict[str, PermissionGroup]:
    group_by_key = {group.key: group for group in PermissionGroup.objects.filter(app=app)}
    for spec in groups:
        parent = group_by_key.get(spec.parent_key) if spec.parent_key else None
        group = group_by_key.get(spec.key)
        if group is None:
            group = PermissionGroup(app=app, key=spec.key)
        group.name = spec.name
        group.parent = parent
        group.depth = spec.depth
        group.display_order = spec.display_order
        group.is_active = True
        group.full_clean()
        group.save()
        group_by_key[spec.key] = group
    return group_by_key


def upsert_permissions(
    app: App,
    permissions: tuple[PermissionSpec, ...],
    group_by_key: dict[str, PermissionGroup],
) -> None:
    incoming_keys = {permission.key for permission in permissions}
    permission_by_key = {
        permission.key: permission for permission in Permission.objects.filter(app=app)
    }
    for spec in permissions:
        permission = permission_by_key.get(spec.key)
        if permission is None:
            permission = Permission(app=app, key=spec.key)
        permission.name = spec.name
        permission.group = group_by_key.get(spec.group_key) if spec.group_key else None
        permission.is_active = True
        permission.deprecated_at = None
        permission.deprecated_reason = ""
        permission.full_clean()
        permission.save()
    _deprecate_missing_permissions(app, incoming_keys)


def record_template_version(
    app: App,
    template: PermissionTemplateInput,
    actions: tuple[TemplateAction, ...],
) -> PermissionTemplateVersion:
    template_version = PermissionTemplateVersion(
        app=app,
        version=template.version,
        source=template.source,
        content_hash=sha256(template.raw_template.encode("utf-8")).hexdigest(),
        raw_template=template.raw_template,
        import_summary={"actions": [action.action for action in actions]},
        imported_by=template.imported_by,
        status=TEMPLATE_STATUS_IMPORTED,
    )
    template_version.full_clean()
    template_version.save()
    return template_version


def record_import_event(
    app: App,
    template: PermissionTemplateInput,
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
                "version": template.version,
                "action_count": len(actions),
            },
        ),
    )


def _deprecate_missing_permissions(app: App, incoming_keys: set[str]) -> None:
    now = timezone.now()
    missing_permissions = Permission.objects.filter(app=app, is_active=True).exclude(
        key__in=incoming_keys,
    )
    for permission in missing_permissions:
        permission.is_active = False
        permission.deprecated_at = now
        permission.deprecated_reason = "permission template missing"
        permission.full_clean()
        permission.save(
            update_fields=["is_active", "deprecated_at", "deprecated_reason", "updated_at"],
        )


def _parent_key(group: PermissionGroup) -> str:
    parent = group.parent
    if parent is None:
        return ""
    return parent.key


def _permission_group_key(permission: Permission) -> str:
    group = permission.group
    if group is None:
        return ""
    return group.key
