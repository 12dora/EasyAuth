from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from easyauth.applications.models import App, ApprovalRule, AuthorizationGroup, Permission

if TYPE_CHECKING:
    from easyauth.admin_console.approval_rule_payloads import TargetType
    from easyauth.api.errors import JsonValue


@dataclass(frozen=True, slots=True)
class ApprovalRuleTarget:
    target_type: TargetType
    target_key: str
    authorization_group: AuthorizationGroup | None
    permission: Permission | None


def approval_rule_target_for_key(
    *,
    app: App,
    target_type: TargetType,
    target_key: str,
) -> ApprovalRuleTarget | None:
    match target_type:
        case "authorization_group":
            authorization_group = AuthorizationGroup.objects.filter(app=app, key=target_key).first()
            if authorization_group is None:
                return None
            return ApprovalRuleTarget(
                target_type="authorization_group",
                target_key=authorization_group.key,
                authorization_group=authorization_group,
                permission=None,
            )
        case "permission":
            permission = Permission.objects.filter(app=app, key=target_key).first()
            if permission is None:
                return None
            return ApprovalRuleTarget(
                target_type="permission",
                target_key=permission.key,
                authorization_group=None,
                permission=permission,
            )


def approval_rule_target(rule: ApprovalRule) -> ApprovalRuleTarget:
    authorization_group = rule.authorization_group
    permission = rule.permission
    if authorization_group is not None:
        return ApprovalRuleTarget(
            target_type="authorization_group",
            target_key=authorization_group.key,
            authorization_group=authorization_group,
            permission=None,
        )
    if permission is not None:
        return ApprovalRuleTarget(
            target_type="permission",
            target_key=permission.key,
            authorization_group=None,
            permission=permission,
        )
    return ApprovalRuleTarget(
        target_type="authorization_group",
        target_key="",
        authorization_group=None,
        permission=None,
    )


def approval_rule_items(app: App) -> list[JsonValue]:
    return [
        approval_rule_item(rule)
        for rule in ApprovalRule.objects.select_related("authorization_group", "permission")
        .filter(app=app)
        .order_by("id")
    ]


def approval_rule_item(rule: ApprovalRule) -> dict[str, JsonValue]:
    target = approval_rule_target(rule)
    approver_userids = _approver_value(rule)
    return {
        "id": _approval_rule_id(rule),
        "target_type": target.target_type,
        "target_key": target.target_key,
        "role_key": _role_key(rule),
        "approver_type": "dingtalk_userids",
        "approver_value": approver_userids,
        "approver_userids": approver_userids,
        "is_active": rule.is_active,
    }


def patched_approvers(
    rule: ApprovalRule,
    approver_userids: tuple[str, ...] | None,
) -> tuple[str, ...]:
    if approver_userids is not None:
        return approver_userids
    return tuple(value for value in _approver_value(rule) if isinstance(value, str))


def _approval_rule_id(rule: ApprovalRule) -> int:
    return rule.id


def _role_key(rule: ApprovalRule) -> str:
    authorization_group = rule.authorization_group
    if authorization_group is None:
        return ""
    return authorization_group.key


def _approver_value(rule: ApprovalRule) -> list[JsonValue]:
    match rule.approver_userids:
        case list() as values:
            return [value for value in values if isinstance(value, str)]
        case _:
            return []
