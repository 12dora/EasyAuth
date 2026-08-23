from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.utils import timezone

from easyauth.applications.catalog_version import bump_catalog_version
from easyauth.applications.manifest_hashing import canonical_manifest_hash_from_template
from easyauth.applications.models import (
    App,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
    PermissionGroup,
    PermissionTemplateVersion,
)
from easyauth.applications.ops_models import TEMPLATE_STATUS_IMPORTED
from easyauth.applications.permission_template_exporting import (
    export_app,
    export_approval_rules,
    export_authorization_groups,
    export_permission_groups,
    export_permissions,
    export_scopes,
    group_parent_key,
    latest_manifest_schema_version,
    permission_group_key,
)
from easyauth.applications.permission_template_types import (
    AppManifestApprovalRuleInput,
    AppManifestAuthorizationGroupInput,
    AppManifestInput,
    AppManifestPermissionGroupInput,
    AppManifestPermissionInput,
    AppManifestScopeInput,
    FlattenedTemplate,
    PermissionTemplateImportError,
    TemplateAction,
)
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from easyauth.applications.models import JsonValue

PERMISSION_TEMPLATE_IMPORTED_EVENT = "app_manifest_imported"


def template_actions(app: App, flattened: FlattenedTemplate) -> tuple[TemplateAction, ...]:
    manifest = flattened.manifest
    actions: list[TemplateAction] = []
    if (
        app.name != manifest.app.name
        or app.description != manifest.app.description
        or app.is_active != manifest.app.is_active
    ):
        actions.append(TemplateAction("update_app", app.app_key))
    actions.extend(_scope_actions(app, manifest))
    actions.extend(_permission_group_actions(app, manifest))
    actions.extend(_permission_actions(app, manifest))
    actions.extend(_authorization_group_actions(app, manifest))
    actions.extend(_approval_rule_actions(app, manifest))
    return tuple(actions)


def upsert_manifest(app: App, manifest: AppManifestInput) -> None:
    _update_app(app, manifest)
    scope_by_key = _upsert_scopes(app, manifest)
    group_by_key = _upsert_permission_groups(app, manifest)
    permission_by_key = _upsert_permissions(app, manifest, group_by_key)
    authorization_group_by_key = _upsert_authorization_groups(app, manifest)
    _upsert_authorization_group_grants(
        manifest=manifest,
        authorization_group_by_key=authorization_group_by_key,
        permission_by_key=permission_by_key,
    )
    _upsert_approval_rules(app, manifest, permission_by_key, authorization_group_by_key)
    _ = scope_by_key


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


@dataclass(frozen=True, slots=True)
class _ActionDiffSpec[ExistingT, IncomingT]:
    create: str
    update: str
    deactivate: str
    changed: Callable[[ExistingT, IncomingT], bool]
    active: Callable[[ExistingT], bool]
    detail: Callable[[IncomingT], str] | None = None


def _diff_actions[ExistingT, IncomingT](
    existing: Mapping[str, ExistingT],
    incoming: Mapping[str, IncomingT],
    spec: _ActionDiffSpec[ExistingT, IncomingT],
) -> list[TemplateAction]:
    actions: list[TemplateAction] = []
    for key, item in incoming.items():
        current = existing.get(key)
        detail = spec.detail(item) if spec.detail is not None else ""
        if current is None:
            actions.append(TemplateAction(spec.create, key, detail))
        elif spec.changed(current, item):
            actions.append(TemplateAction(spec.update, key, detail))
    actions.extend(
        TemplateAction(spec.deactivate, key)
        for key, current in sorted(existing.items())
        if key not in incoming and spec.active(current)
    )
    return actions


def _scope_changed(current: AppScope, scope: AppManifestScopeInput) -> bool:
    return (
        current.name != scope.name
        or current.name_en != scope.name_en
        or current.description != scope.description
        or current.description_en != scope.description_en
        or current.is_active != scope.is_active
        or current.display_order != scope.display_order
    )


def _permission_group_changed(
    current: PermissionGroup,
    group: AppManifestPermissionGroupInput,
) -> bool:
    return (
        current.name != group.name
        or current.name_en != group.name_en
        or current.description != group.description
        or current.description_en != group.description_en
        or group_parent_key(current) != group.parent_key
        or current.display_order != group.display_order
        or current.is_active != group.is_active
    )


def _permission_changed(
    current: Permission,
    permission: AppManifestPermissionInput,
) -> bool:
    return (
        current.name != permission.name
        or current.name_en != permission.name_en
        or current.description != permission.description
        or current.description_en != permission.description_en
        or permission_group_key(current) != permission.group_key
        or current.supported_scopes != list(permission.supported_scopes)
        or current.risk_level != permission.risk_level
        or current.is_active != permission.is_active
    )


def _authorization_group_changed(
    current: AuthorizationGroup,
    group: AppManifestAuthorizationGroupInput,
) -> bool:
    return (
        current.kind != group.kind
        or current.name != group.name
        or current.name_en != group.name_en
        or current.description != group.description
        or current.description_en != group.description_en
        or current.requestable != group.requestable
        or current.is_active != group.is_active
        or _grant_set(current) != _incoming_grant_set(group)
    )


def _scope_actions(app: App, manifest: AppManifestInput) -> list[TemplateAction]:
    existing = {scope.key: scope for scope in AppScope.objects.filter(app=app)}
    incoming = {scope.key: scope for scope in manifest.scopes}
    return _diff_actions(
        existing,
        incoming,
        _ActionDiffSpec(
            create="create_scope",
            update="update_scope",
            deactivate="deactivate_scope",
            changed=_scope_changed,
            active=lambda scope: scope.is_active,
        ),
    )


def _permission_group_actions(app: App, manifest: AppManifestInput) -> list[TemplateAction]:
    existing = {group.key: group for group in PermissionGroup.objects.filter(app=app)}
    incoming = {group.key: group for group in manifest.permission_groups}
    return _diff_actions(
        existing,
        incoming,
        _ActionDiffSpec(
            create="create_permission_group",
            update="update_permission_group",
            deactivate="deactivate_permission_group",
            changed=_permission_group_changed,
            active=lambda group: group.is_active,
            detail=lambda group: group.parent_key,
        ),
    )


def _permission_actions(app: App, manifest: AppManifestInput) -> list[TemplateAction]:
    existing = {permission.key: permission for permission in Permission.objects.filter(app=app)}
    incoming = {permission.key: permission for permission in manifest.permissions}
    return _diff_actions(
        existing,
        incoming,
        _ActionDiffSpec(
            create="create_permission",
            update="update_permission",
            deactivate="deactivate_permission",
            changed=_permission_changed,
            active=lambda permission: permission.is_active,
            detail=lambda permission: permission.group_key,
        ),
    )


def _authorization_group_actions(app: App, manifest: AppManifestInput) -> list[TemplateAction]:
    existing = {
        authorization_group.key: authorization_group
        for authorization_group in AuthorizationGroup.objects.filter(app=app)
    }
    incoming = {group.key: group for group in manifest.authorization_groups}
    return _diff_actions(
        existing,
        incoming,
        _ActionDiffSpec(
            create="create_authorization_group",
            update="update_authorization_group",
            deactivate="deactivate_authorization_group",
            changed=_authorization_group_changed,
            active=lambda group: group.is_active,
        ),
    )


def _approval_rule_actions(app: App, manifest: AppManifestInput) -> list[TemplateAction]:
    actions: list[TemplateAction] = []
    existing = {_approval_rule_key(rule): rule for rule in ApprovalRule.objects.filter(app=app)}
    incoming = {_approval_rule_input_key(rule): rule for rule in manifest.approval_rules}
    for key, rule in incoming.items():
        current = existing.get(key)
        if current is None:
            actions.append(TemplateAction("create_approval_rule", key))
        elif (
            current.approver_userids != list(rule.approver_userids)
            or current.is_active != rule.is_active
        ):
            actions.append(TemplateAction("update_approval_rule", key))
    actions.extend(
        TemplateAction("deactivate_approval_rule", key)
        for key, current in sorted(existing.items())
        if key not in incoming and current.is_active
    )
    return actions


def _update_app(app: App, manifest: AppManifestInput) -> None:
    app.name = manifest.app.name
    app.description = manifest.app.description
    app.is_active = manifest.app.is_active
    app.full_clean()
    app.save(update_fields=["name", "description", "is_active", "updated_at"])


def _upsert_scopes(app: App, manifest: AppManifestInput) -> dict[str, AppScope]:
    incoming = {scope.key: scope for scope in manifest.scopes}
    scope_by_key = {scope.key: scope for scope in AppScope.objects.filter(app=app)}
    for key, spec in incoming.items():
        scope = scope_by_key.get(key) or AppScope(app=app, key=key)
        scope.name = spec.name
        scope.name_en = spec.name_en
        scope.description = spec.description
        scope.description_en = spec.description_en
        scope.is_active = spec.is_active
        scope.display_order = spec.display_order
        scope.full_clean()
        scope.save()
        scope_by_key[key] = scope
    for key, scope in scope_by_key.items():
        if key not in incoming and scope.is_active:
            scope.is_active = False
            scope.full_clean()
            scope.save(update_fields=["is_active", "updated_at"])
    return scope_by_key


def _upsert_permission_groups(
    app: App,
    manifest: AppManifestInput,
) -> dict[str, PermissionGroup]:
    depth_by_key = _permission_group_depths(manifest.permission_groups)
    incoming_keys = {spec.key for spec in manifest.permission_groups}
    group_by_key = {group.key: group for group in PermissionGroup.objects.filter(app=app)}
    for spec in manifest.permission_groups:
        group = group_by_key.get(spec.key)
        if group is None:
            group = PermissionGroup(app=app, key=spec.key, depth=1)
        group.name = spec.name
        group.name_en = spec.name_en
        group.description = spec.description
        group.description_en = spec.description_en
        group.display_order = spec.display_order
        group.is_active = spec.is_active
        group.parent = None
        group.depth = 1
        group.full_clean(exclude=["parent"])
        group.save()
        group_by_key[spec.key] = group
    for spec in sorted(manifest.permission_groups, key=lambda group: depth_by_key[group.key]):
        group = group_by_key[spec.key]
        group.parent = group_by_key.get(spec.parent_key) if spec.parent_key else None
        group.depth = depth_by_key[spec.key]
        group.full_clean()
        group.save(update_fields=["parent", "depth", "updated_at"])
    _detach_missing_permission_group_roots(app, incoming_keys)
    _sync_permission_group_depths(app)
    group_by_key = {group.key: group for group in PermissionGroup.objects.filter(app=app)}
    for key, group in group_by_key.items():
        if key not in incoming_keys and group.is_active:
            group.is_active = False
            group.full_clean()
            group.save(update_fields=["is_active", "updated_at"])
    return group_by_key


def _upsert_permissions(
    app: App,
    manifest: AppManifestInput,
    group_by_key: dict[str, PermissionGroup],
) -> dict[str, Permission]:
    now = timezone.now()
    incoming = {permission.key: permission for permission in manifest.permissions}
    permission_by_key = {
        permission.key: permission for permission in Permission.objects.filter(app=app)
    }
    for key, spec in incoming.items():
        permission = permission_by_key.get(key) or Permission(app=app, key=key)
        permission.name = spec.name
        permission.name_en = spec.name_en
        permission.description = spec.description
        permission.description_en = spec.description_en
        permission.group = group_by_key.get(spec.group_key)
        permission.supported_scopes = list(spec.supported_scopes)
        permission.risk_level = spec.risk_level
        permission.is_active = spec.is_active
        permission.deprecated_at = None if spec.is_active else permission.deprecated_at
        permission.deprecated_reason = "" if spec.is_active else permission.deprecated_reason
        permission.full_clean()
        permission.save()
        permission_by_key[key] = permission
    for key, permission in permission_by_key.items():
        if key not in incoming and permission.is_active:
            permission.is_active = False
            permission.deprecated_at = now
            permission.deprecated_reason = "app manifest missing"
            permission.full_clean()
            permission.save(
                update_fields=["is_active", "deprecated_at", "deprecated_reason", "updated_at"],
            )
    return permission_by_key


def _upsert_authorization_groups(
    app: App,
    manifest: AppManifestInput,
) -> dict[str, AuthorizationGroup]:
    incoming = {group.key: group for group in manifest.authorization_groups}
    group_by_key = {group.key: group for group in AuthorizationGroup.objects.filter(app=app)}
    for key, spec in incoming.items():
        group = group_by_key.get(key) or AuthorizationGroup(app=app, key=key)
        group.kind = spec.kind
        group.name = spec.name
        group.name_en = spec.name_en
        group.description = spec.description
        group.description_en = spec.description_en
        group.requestable = spec.requestable
        group.is_active = spec.is_active
        group.full_clean()
        group.save()
        group_by_key[key] = group
    for key, group in group_by_key.items():
        if key not in incoming and group.is_active:
            group.is_active = False
            group.full_clean()
            group.save(update_fields=["is_active", "updated_at"])
    return group_by_key


def _upsert_authorization_group_grants(
    *,
    manifest: AppManifestInput,
    authorization_group_by_key: dict[str, AuthorizationGroup],
    permission_by_key: dict[str, Permission],
) -> None:
    incoming_grants = {
        (group.key, grant.permission, grant.scope): grant
        for group in manifest.authorization_groups
        for grant in group.grants
    }
    existing_grants = {
        (grant.authorization_group.key, grant.permission.key, grant.scope_key): grant
        for grant in AuthorizationGroupGrant.objects.filter(
            authorization_group__in=authorization_group_by_key.values(),
        ).select_related("authorization_group", "permission")
    }
    for (group_key, permission_key, scope_key), spec in incoming_grants.items():
        grant = existing_grants.get(
            (group_key, permission_key, scope_key),
        ) or AuthorizationGroupGrant(
            authorization_group=authorization_group_by_key[group_key],
            permission=permission_by_key[permission_key],
            scope_key=scope_key,
        )
        grant.is_active = spec.is_active
        grant.full_clean()
        grant.save()
    for key, grant in existing_grants.items():
        if key not in incoming_grants and grant.is_active:
            grant.is_active = False
            grant.full_clean()
            grant.save(update_fields=["is_active", "updated_at"])


def _upsert_approval_rules(
    app: App,
    manifest: AppManifestInput,
    permission_by_key: dict[str, Permission],
    authorization_group_by_key: dict[str, AuthorizationGroup],
) -> None:
    incoming = {_approval_rule_input_key(rule): rule for rule in manifest.approval_rules}
    existing = {_approval_rule_key(rule): rule for rule in ApprovalRule.objects.filter(app=app)}
    for key, spec in incoming.items():
        rule = existing.get(key) or ApprovalRule(app=app)
        if spec.target_type == "authorization_group":
            rule.authorization_group = authorization_group_by_key[spec.target_key]
            rule.permission = None
        else:
            rule.authorization_group = None
            rule.permission = permission_by_key[spec.target_key]
        rule.approver_userids = list(spec.approver_userids)
        rule.is_active = spec.is_active
        rule.full_clean()
        rule.save()
    for key, rule in existing.items():
        if key not in incoming and rule.is_active:
            rule.is_active = False
            rule.full_clean()
            rule.save(update_fields=["is_active", "updated_at"])


def _permission_group_depths(
    groups: tuple[AppManifestPermissionGroupInput, ...],
) -> dict[str, int]:
    group_by_key = {group.key: group for group in groups}
    depths: dict[str, int] = {}

    def depth_for(key: str, stack: tuple[str, ...] = ()) -> int:
        if key in depths:
            return depths[key]
        if key in stack:
            raise PermissionTemplateImportError(
                code="app_manifest_permission_group_cycle",
                message="App manifest permission group 不能形成环。",
                subject=key,
            )
        parent_key = group_by_key[key].parent_key
        depth = 1 if not parent_key else depth_for(parent_key, (*stack, key)) + 1
        depths[key] = depth
        return depth

    for group in groups:
        _ = depth_for(group.key)
    return depths


def _sync_permission_group_depths(app: App) -> None:
    groups = list(PermissionGroup.objects.filter(app=app).select_related("parent"))
    group_by_id = {group.id: group for group in groups}
    depth_by_id: dict[int, int] = {}

    def depth_for(group: PermissionGroup) -> int:
        if group.id in depth_by_id:
            return depth_by_id[group.id]
        parent_id = group.parent_id
        depth = 1 if parent_id is None else depth_for(group_by_id[parent_id]) + 1
        depth_by_id[group.id] = depth
        return depth

    for group in groups:
        _ = depth_for(group)

    for group in sorted(groups, key=lambda item: depth_by_id[item.id]):
        expected_depth = depth_by_id[group.id]
        if group.depth == expected_depth:
            continue
        group.depth = expected_depth
        if group.parent_id is not None:
            group.parent = group_by_id[group.parent_id]
        group.full_clean()
        group.save(update_fields=["depth", "updated_at"])


def _detach_missing_permission_group_roots(app: App, incoming_keys: set[str]) -> None:
    group_by_key = {group.key: group for group in PermissionGroup.objects.filter(app=app)}
    incoming_ids = {group_by_key[key].id for key in incoming_keys}
    for key, group in group_by_key.items():
        if key in incoming_keys or group.parent_id not in incoming_ids:
            continue
        group.parent = None
        group.depth = 1
        group.full_clean()
        group.save(update_fields=["parent", "depth", "updated_at"])


def _grant_set(group: AuthorizationGroup) -> set[tuple[str, str, bool]]:
    grants = AuthorizationGroupGrant.objects.filter(authorization_group=group).select_related(
        "permission",
    )
    return {
        (grant.permission.key, grant.scope_key, grant.is_active)
        for grant in grants
    }


def _incoming_grant_set(group: AppManifestAuthorizationGroupInput) -> set[tuple[str, str, bool]]:
    return {(grant.permission, grant.scope, grant.is_active) for grant in group.grants}


def _approval_rule_key(rule: ApprovalRule) -> str:
    if rule.authorization_group_id:
        authorization_group = rule.authorization_group
        if authorization_group is None:
            return f"unknown:{rule.id}"
        return f"authorization_group:{authorization_group.key}"
    if rule.permission_id:
        permission = rule.permission
        if permission is None:
            return f"unknown:{rule.id}"
        return f"permission:{permission.key}"
    return f"unknown:{rule.id}"


def _approval_rule_input_key(rule: AppManifestApprovalRuleInput) -> str:
    return f"{rule.target_type}:{rule.target_key}"
