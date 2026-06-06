from __future__ import annotations

from dataclasses import dataclass
from typing import override

from django.db import transaction

from easyauth.applications.models import App, ApprovalRule, Permission, Role, RolePermission
from easyauth.audit.services import AuditRecord, AuditService


@dataclass(frozen=True, slots=True)
class ConsoleMutationActor:
    actor_id: str


@dataclass(frozen=True, slots=True)
class RolePermissionMutation:
    app: App
    role: Role
    permission: Permission
    enabled: bool
    actor: ConsoleMutationActor


@dataclass(frozen=True, slots=True)
class ApprovalRuleMutation:
    app: App
    rule: ApprovalRule
    role: Role | None
    permission: Permission | None
    approver_userids: tuple[str, ...]
    is_active: bool
    actor: ConsoleMutationActor


@dataclass(frozen=True, slots=True)
class ApprovalRuleCreateMutation:
    app: App
    role: Role | None
    permission: Permission | None
    approver_userids: tuple[str, ...]
    is_active: bool
    actor: ConsoleMutationActor


@dataclass(frozen=True, slots=True)
class ConsoleConfigurationError(Exception):
    code: str

    @override
    def __str__(self) -> str:
        return self.code


@transaction.atomic
def set_role_permission(input_data: RolePermissionMutation) -> None:
    if input_data.role.app_id != input_data.app.id:
        raise ConsoleConfigurationError(code="role_app_mismatch")
    if input_data.permission.app_id != input_data.app.id:
        raise ConsoleConfigurationError(code="permission_app_mismatch")

    link = RolePermission.objects.filter(
        role=input_data.role,
        permission=input_data.permission,
    ).first()
    if input_data.enabled and link is None:
        link = RolePermission(role=input_data.role, permission=input_data.permission)
        link.full_clean()
        link.save()
    if not input_data.enabled and link is not None:
        _ = link.delete()

    metadata: dict[str, str | bool | int] = {
        "role_key": input_data.role.key,
        "permission_key": input_data.permission.key,
        "enabled": input_data.enabled,
    }
    _record_config_event(
        action="role_permission_matrix_updated",
        app=input_data.app,
        actor=input_data.actor,
        metadata=metadata,
    )
    _record_config_event(
        action="role_permission_matrix_changed",
        app=input_data.app,
        actor=input_data.actor,
        metadata=metadata,
    )


@transaction.atomic
def create_role(
    *,
    app: App,
    key: str,
    name: str,
    requestable: bool,
    actor: ConsoleMutationActor,
) -> Role:
    role = Role(app=app, key=key, name=name, requestable=requestable)
    role.full_clean()
    role.save()
    _record_config_event(
        action="role_created",
        app=app,
        actor=actor,
        metadata={"role_key": role.key, "requestable": role.requestable},
    )
    return role


@transaction.atomic
def create_permission(
    *,
    app: App,
    key: str,
    name: str,
    actor: ConsoleMutationActor,
) -> Permission:
    permission = Permission(app=app, key=key, name=name)
    permission.full_clean()
    permission.save()
    _record_config_event(
        action="permission_created",
        app=app,
        actor=actor,
        metadata={"permission_key": permission.key},
    )
    return permission


@transaction.atomic
def create_approval_rule(input_data: ApprovalRuleCreateMutation) -> ApprovalRule:
    rule = ApprovalRule(
        app=input_data.app,
        role=input_data.role,
        permission=input_data.permission,
        approver_userids=list(input_data.approver_userids),
        is_active=input_data.is_active,
    )
    rule.full_clean()
    rule.save()
    _record_config_event(
        action="approval_rule_created",
        app=input_data.app,
        actor=input_data.actor,
        metadata=_approval_rule_metadata(
            role=input_data.role,
            permission=input_data.permission,
            approver_count=len(input_data.approver_userids),
        ),
    )
    return rule


@transaction.atomic
def update_approval_rule(input_data: ApprovalRuleMutation) -> ApprovalRule:
    if input_data.rule.app != input_data.app:
        raise ConsoleConfigurationError(code="approval_rule_app_mismatch")
    if input_data.role is not None and input_data.role.app_id != input_data.app.id:
        raise ConsoleConfigurationError(code="role_app_mismatch")
    if input_data.permission is not None and input_data.permission.app_id != input_data.app.id:
        raise ConsoleConfigurationError(code="permission_app_mismatch")

    input_data.rule.role = input_data.role
    input_data.rule.permission = input_data.permission
    input_data.rule.approver_userids = list(input_data.approver_userids)
    input_data.rule.is_active = input_data.is_active
    input_data.rule.full_clean()
    input_data.rule.save(update_fields=["role", "permission", "approver_userids", "is_active"])
    _record_config_event(
        action="approval_rule_updated",
        app=input_data.app,
        actor=input_data.actor,
        metadata=_approval_rule_metadata(
            role=input_data.role,
            permission=input_data.permission,
            approver_count=len(input_data.approver_userids),
            is_active=input_data.is_active,
        ),
    )
    return input_data.rule


def _approval_rule_metadata(
    *,
    role: Role | None,
    permission: Permission | None,
    approver_count: int,
    is_active: bool | None = None,
) -> dict[str, str | bool | int]:
    metadata: dict[str, str | bool | int] = {"approver_count": approver_count}
    if role is not None:
        metadata["target_type"] = "role"
        metadata["target_key"] = role.key
        metadata["role_key"] = role.key
    if permission is not None:
        metadata["target_type"] = "permission"
        metadata["target_key"] = permission.key
        metadata["permission_key"] = permission.key
    if is_active is not None:
        metadata["is_active"] = is_active
    return metadata


def _record_config_event(
    *,
    action: str,
    app: App,
    actor: ConsoleMutationActor,
    metadata: dict[str, str | bool | int],
) -> None:
    stored_metadata: dict[str, str | bool | int] = {"app_key": app.app_key}
    stored_metadata.update(metadata)
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=actor.actor_id,
            action=action,
            target_type="app",
            target_id=str(app.id),
            metadata=stored_metadata,
        ),
    )
