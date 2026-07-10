from __future__ import annotations

from dataclasses import dataclass
from typing import override

from django.db import transaction

from easyauth.applications.catalog_version import bump_catalog_version
from easyauth.applications.models import (
    App,
    ApprovalRule,
    AuthorizationGroup,
    Permission,
)
from easyauth.audit.services import AuditRecord, AuditService


@dataclass(frozen=True, slots=True)
class ConsoleMutationActor:
    actor_id: str


@dataclass(frozen=True, slots=True)
class ApprovalRuleMutation:
    app: App
    rule: ApprovalRule
    authorization_group: AuthorizationGroup | None
    permission: Permission | None
    approver_userids: tuple[str, ...]
    is_active: bool
    actor: ConsoleMutationActor


@dataclass(frozen=True, slots=True)
class ApprovalRuleCreateMutation:
    app: App
    authorization_group: AuthorizationGroup | None
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
        authorization_group=input_data.authorization_group,
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
            authorization_group=input_data.authorization_group,
            permission=input_data.permission,
            approver_count=len(input_data.approver_userids),
        ),
    )
    bump_catalog_version(
        input_data.app,
        actor_id=input_data.actor.actor_id,
        reason="approval_rule_created",
        metadata=_approval_rule_metadata(
            authorization_group=input_data.authorization_group,
            permission=input_data.permission,
            approver_count=len(input_data.approver_userids),
        ),
    )
    return rule


@transaction.atomic
def update_approval_rule(input_data: ApprovalRuleMutation) -> ApprovalRule:
    if input_data.rule.app != input_data.app:
        raise ConsoleConfigurationError(code="approval_rule_app_mismatch")
    if (
        input_data.authorization_group is not None
        and input_data.authorization_group.app_id != input_data.app.id
    ):
        raise ConsoleConfigurationError(code="authorization_group_app_mismatch")
    if input_data.permission is not None and input_data.permission.app_id != input_data.app.id:
        raise ConsoleConfigurationError(code="permission_app_mismatch")

    input_data.rule.authorization_group = input_data.authorization_group
    input_data.rule.permission = input_data.permission
    input_data.rule.approver_userids = list(input_data.approver_userids)
    input_data.rule.is_active = input_data.is_active
    input_data.rule.full_clean()
    input_data.rule.save(
        update_fields=[
            "authorization_group",
            "permission",
            "approver_userids",
            "is_active",
        ],
    )
    _record_config_event(
        action="approval_rule_updated",
        app=input_data.app,
        actor=input_data.actor,
        metadata=_approval_rule_metadata(
            authorization_group=input_data.authorization_group,
            permission=input_data.permission,
            approver_count=len(input_data.approver_userids),
            is_active=input_data.is_active,
        ),
    )
    bump_catalog_version(
        input_data.app,
        actor_id=input_data.actor.actor_id,
        reason="approval_rule_updated",
        metadata=_approval_rule_metadata(
            authorization_group=input_data.authorization_group,
            permission=input_data.permission,
            approver_count=len(input_data.approver_userids),
            is_active=input_data.is_active,
        ),
    )
    return input_data.rule


def _approval_rule_metadata(
    *,
    authorization_group: AuthorizationGroup | None,
    permission: Permission | None,
    approver_count: int,
    is_active: bool | None = None,
) -> dict[str, str | bool | int]:
    metadata: dict[str, str | bool | int] = {"approver_count": approver_count}
    if authorization_group is not None:
        metadata["target_type"] = "authorization_group"
        metadata["target_key"] = authorization_group.key
        metadata["authorization_group_key"] = authorization_group.key
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
