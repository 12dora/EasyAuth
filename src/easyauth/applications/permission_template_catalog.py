"""把 AppManifestInput 写入 App / scope / permission / 授权组 / 审批规则目录。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils import timezone

from easyauth.applications.models import (
    App,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    Permission,
    PermissionGroup,
)
from easyauth.applications.permission_template_diff import (
    _approval_rule_input_key,
    _approval_rule_key,
)
from easyauth.applications.permission_template_grant_upsert import (
    _upsert_authorization_group_grants,
)
from easyauth.applications.permission_template_group_upsert import _upsert_permission_groups

if TYPE_CHECKING:
    from easyauth.applications.permission_template_types import AppManifestInput

__all__ = ["upsert_manifest"]


def upsert_manifest(app: App, manifest: AppManifestInput) -> None:
    _update_app(app, manifest)
    _ = _upsert_scopes(app, manifest)
    group_by_key = _upsert_permission_groups(app, manifest)
    permission_by_key = _upsert_permissions(app, manifest, group_by_key)
    authorization_group_by_key = _upsert_authorization_groups(app, manifest)
    _upsert_authorization_group_grants(
        manifest=manifest,
        authorization_group_by_key=authorization_group_by_key,
        permission_by_key=permission_by_key,
    )
    _upsert_approval_rules(app, manifest, permission_by_key, authorization_group_by_key)


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


def _upsert_approval_rules(
    app: App,
    manifest: AppManifestInput,
    permission_by_key: dict[str, Permission],
    authorization_group_by_key: dict[str, AuthorizationGroup],
) -> None:
    incoming = {_approval_rule_input_key(rule): rule for rule in manifest.approval_rules}
    existing = {
        _approval_rule_key(rule): rule
        for rule in ApprovalRule.objects.filter(app=app).select_related(
            "authorization_group",
            "permission",
        )
    }
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
