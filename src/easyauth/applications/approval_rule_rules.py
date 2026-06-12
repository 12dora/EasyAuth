from __future__ import annotations

from typing import Protocol, cast


class _BoundApp(Protocol):
    id: int


class _ApprovalTarget(Protocol):
    app: _BoundApp


class _ApprovalRule(Protocol):
    app: _BoundApp
    role: _ApprovalTarget | None
    permission: _ApprovalTarget | None
    approver_userids: object


def approval_rule_clean_errors(rule: object) -> dict[str, str]:
    typed_rule = cast("_ApprovalRule", rule)
    errors: dict[str, str] = {}
    role = typed_rule.role
    permission = typed_rule.permission
    has_role = role is not None
    has_permission = permission is not None

    if has_role == has_permission:
        errors["role"] = "Approval rule must target exactly one role or permission."
        errors["permission"] = "Approval rule must target exactly one role or permission."
    if role is not None and role.app != typed_rule.app:
        errors["role"] = "Role must belong to the approval rule app."
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
