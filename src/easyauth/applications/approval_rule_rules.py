from __future__ import annotations

from typing import Protocol, cast


class _BoundApp(Protocol):
    id: int


class _ApprovalTarget(Protocol):
    app: _BoundApp


class _ApprovalRule(Protocol):
    app: _BoundApp
    authorization_group: _ApprovalTarget | None
    permission: _ApprovalTarget | None
    approver_userids: object


def approval_rule_clean_errors(rule: object) -> dict[str, str]:
    typed_rule = cast("_ApprovalRule", rule)
    authorization_group = typed_rule.authorization_group
    permission = typed_rule.permission
    errors = _approval_target_errors(
        typed_rule,
        authorization_group=authorization_group,
        permission=permission,
    )
    if not _valid_approver_userids(typed_rule.approver_userids):
        errors["approver_userids"] = "DingTalk approver userids must be a non-empty list."
    return errors


def _approval_target_errors(
    rule: _ApprovalRule,
    *,
    authorization_group: _ApprovalTarget | None,
    permission: _ApprovalTarget | None,
) -> dict[str, str]:
    errors: dict[str, str] = {}
    target_count = sum(
        target is not None for target in (authorization_group, permission)
    )

    if target_count != 1:
        message = "Approval rule must target exactly one authorization group or permission."
        errors["authorization_group"] = message
        errors["permission"] = message
    if authorization_group is not None and authorization_group.app != rule.app:
        errors["authorization_group"] = (
            "Authorization group must belong to the approval rule app."
        )
    if permission is not None and permission.app != rule.app:
        errors["permission"] = "Permission must belong to the approval rule app."
    return errors


def _valid_approver_userids(value: object) -> bool:
    if not isinstance(value, list):
        return False
    approver_userids = cast("list[object]", value)
    return bool(approver_userids) and all(
        isinstance(userid, str) and userid for userid in approver_userids
    )
