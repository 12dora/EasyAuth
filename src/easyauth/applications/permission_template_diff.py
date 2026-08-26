"""对比现有目录与 incoming manifest, 生成 preview/apply 共用的 TemplateAction。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from easyauth.applications.models import (
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    Permission,
    PermissionGroup,
)
from easyauth.applications.permission_template_exporting import (
    group_parent_key,
    permission_group_key,
)
from easyauth.applications.permission_template_grant_upsert import (
    _grant_sets_by_group_id,
    _incoming_grant_set,
)
from easyauth.applications.permission_template_types import TemplateAction

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from easyauth.applications.models import App
    from easyauth.applications.permission_template_types import (
        AppManifestApprovalRuleInput,
        AppManifestAuthorizationGroupInput,
        AppManifestInput,
        AppManifestPermissionGroupInput,
        AppManifestPermissionInput,
        AppManifestScopeInput,
        FlattenedTemplate,
    )

type _GrantFingerprint = tuple[str, str, bool]

__all__ = [
    "_approval_rule_input_key",
    "_approval_rule_key",
    "template_actions",
]


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
    current_grants: set[_GrantFingerprint],
) -> bool:
    return (
        current.kind != group.kind
        or current.name != group.name
        or current.name_en != group.name_en
        or current.description != group.description
        or current.description_en != group.description_en
        or current.requestable != group.requestable
        or current.is_active != group.is_active
        or current_grants != _incoming_grant_set(group)
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
    existing = {
        group.key: group
        for group in PermissionGroup.objects.filter(app=app).select_related("parent")
    }
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
    existing = {
        permission.key: permission
        for permission in Permission.objects.filter(app=app).select_related("group")
    }
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
    grant_sets_by_group_id = _grant_sets_by_group_id(app)
    incoming = {group.key: group for group in manifest.authorization_groups}

    def changed(
        current: AuthorizationGroup,
        group: AppManifestAuthorizationGroupInput,
    ) -> bool:
        return _authorization_group_changed(
            current,
            group,
            grant_sets_by_group_id.get(current.id, set()),
        )

    return _diff_actions(
        existing,
        incoming,
        _ActionDiffSpec(
            create="create_authorization_group",
            update="update_authorization_group",
            deactivate="deactivate_authorization_group",
            changed=changed,
            active=lambda group: group.is_active,
        ),
    )


def _approval_rule_actions(app: App, manifest: AppManifestInput) -> list[TemplateAction]:
    actions: list[TemplateAction] = []
    existing = {
        _approval_rule_key(rule): rule
        for rule in ApprovalRule.objects.filter(app=app).select_related(
            "authorization_group",
            "permission",
        )
    }
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
