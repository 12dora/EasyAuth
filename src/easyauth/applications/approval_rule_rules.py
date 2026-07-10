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
    errors: dict[str, str] = {}
    authorization_group = typed_rule.authorization_group
    permission = typed_rule.permission
    target_count = sum(
        target is not None for target in (authorization_group, permission)
    )

    if target_count != 1:
        message = "Approval rule must target exactly one authorization group or permission."
        errors["authorization_group"] = message
        errors["permission"] = message
    if authorization_group is not None and authorization_group.app != typed_rule.app:
        errors["authorization_group"] = (
            "Authorization group must belong to the approval rule app."
        )
    if permission is not None and permission.app != typed_rule.app:
        errors["permission"] = "Permission must belong to the approval rule app."

    approver_userids_value = typed_rule.approver_userids
    valid_approver_userids = False
    if isinstance(approver_userids_value, list):
        approver_userids = cast("list[object]", approver_userids_value)
        valid_approver_userids = bool(approver_userids) and all(
            isinstance(userid, str) and userid for userid in approver_userids
        )
    if not valid_approver_userids:
        errors["approver_userids"] = "DingTalk approver userids must be a non-empty list."

    return errors
