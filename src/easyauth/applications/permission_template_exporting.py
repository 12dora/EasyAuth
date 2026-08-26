from __future__ import annotations

from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from easyauth.applications.models import JsonValue


def latest_manifest_schema_version(app: App) -> int:
    latest = PermissionTemplateVersion.objects.filter(app=app).order_by("-version").first()
    return latest.version if latest is not None else 1


def export_app(app: App) -> dict[str, JsonValue]:
    return {
        "app_key": app.app_key,
        "name": app.name,
        "description": app.description,
        "is_active": app.is_active,
    }


def export_scopes(app: App) -> list[JsonValue]:
    return [
        {
            "key": scope.key,
            "name": scope.name,
            "description": scope.description,
            **_bilingual_export_fields(
                name_en=scope.name_en,
                description_en=scope.description_en,
            ),
            "is_active": scope.is_active,
            "display_order": scope.display_order,
        }
        for scope in AppScope.objects.filter(app=app).order_by("display_order", "key")
    ]


def export_permission_groups(app: App) -> list[JsonValue]:
    return [
        {
            "key": group.key,
            "name": group.name,
            "description": group.description,
            **_bilingual_export_fields(
                name_en=group.name_en,
                description_en=group.description_en,
            ),
            "parent_key": group_parent_key(group),
            "display_order": group.display_order,
            "is_active": group.is_active,
        }
        for group in PermissionGroup.objects.filter(app=app)
        .select_related("parent")
        .order_by("display_order", "key")
    ]


def export_permissions(app: App) -> list[JsonValue]:
    return [
        {
            "key": permission.key,
            "name": permission.name,
            "description": permission.description,
            **_bilingual_export_fields(
                name_en=permission.name_en,
                description_en=permission.description_en,
            ),
            "group_key": permission_group_key(permission),
            "supported_scopes": permission.supported_scopes,
            "risk_level": permission.risk_level,
            "is_active": permission.is_active,
        }
        for permission in Permission.objects.filter(app=app).select_related("group").order_by("key")
    ]


def export_authorization_groups(app: App) -> list[JsonValue]:
    return [
        _export_authorization_group(group)
        for group in AuthorizationGroup.objects.filter(app=app).order_by("kind", "key")
    ]


def export_approval_rules(app: App) -> list[JsonValue]:
    return [
        exported
        for rule in ApprovalRule.objects.filter(app=app)
        .select_related("authorization_group", "permission")
        .order_by("id")
        if (exported := _export_approval_rule(rule)) is not None
    ]


def _bilingual_export_fields(*, name_en: str, description_en: str) -> dict[str, str]:
    # 导出的 manifest 只在双语字段非空时输出对应键, 保持导出干净且可直接回放导入。
    fields: dict[str, str] = {}
    if name_en:
        fields["name_en"] = name_en
    if description_en:
        fields["description_en"] = description_en
    return fields


def _export_authorization_group(group: AuthorizationGroup) -> dict[str, JsonValue]:
    return {
        "key": group.key,
        "kind": group.kind,
        "name": group.name,
        "description": group.description,
        **_bilingual_export_fields(name_en=group.name_en, description_en=group.description_en),
        "requestable": group.requestable,
        "is_active": group.is_active,
        "grants": [
            {
                "permission": grant.permission.key,
                "scope": grant.scope_key,
                "is_active": grant.is_active,
            }
            for grant in AuthorizationGroupGrant.objects.filter(authorization_group=group)
            .select_related("permission")
            .order_by(
                "permission__key",
                "scope_key",
            )
        ],
    }


def _export_approval_rule(rule: ApprovalRule) -> dict[str, JsonValue] | None:
    if rule.authorization_group_id:
        authorization_group = rule.authorization_group
        if authorization_group is None:
            return None
        return {
            "target_type": "authorization_group",
            "target_key": authorization_group.key,
            "approver_userids": rule.approver_userids,
            "is_active": rule.is_active,
        }
    if rule.permission_id:
        permission = rule.permission
        if permission is None:
            return None
        return {
            "target_type": "permission",
            "target_key": permission.key,
            "approver_userids": rule.approver_userids,
            "is_active": rule.is_active,
        }
    return None


def group_parent_key(group: PermissionGroup) -> str:
    parent = group.parent
    return parent.key if parent is not None else ""


def permission_group_key(permission: Permission) -> str:
    group = permission.group
    return group.key if group is not None else ""
