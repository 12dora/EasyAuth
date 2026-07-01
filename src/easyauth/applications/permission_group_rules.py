from __future__ import annotations

from typing import Final, Protocol, cast

PERMISSION_GROUP_MAX_DEPTH: Final = 5


class PermissionGroupRuleTarget(Protocol):
    id: int
    app_id: int
    depth: int
    parent: PermissionGroupRuleTarget | None


def permission_group_has_cycle(
    group: PermissionGroupRuleTarget,
    parent: PermissionGroupRuleTarget,
) -> bool:
    ancestor: PermissionGroupRuleTarget | None = parent
    while ancestor is not None:
        if ancestor.id == group.id:
            return True
        ancestor = ancestor.parent
    return False


def permission_group_clean_errors(group: object) -> dict[str, str]:
    typed_group = cast("PermissionGroupRuleTarget", group)
    errors: dict[str, str] = {}
    parent = typed_group.parent
    if parent is None:
        expected_depth = 1
    else:
        if parent.app_id != typed_group.app_id:
            errors["parent"] = "Permission group parent must belong to the same app."
        expected_depth = parent.depth + 1
        if permission_group_has_cycle(typed_group, parent):
            errors["parent"] = "Permission group tree cannot contain cycles."
    if typed_group.depth != expected_depth:
        errors["depth"] = "Permission group depth must match its parent."
    if typed_group.depth > PERMISSION_GROUP_MAX_DEPTH:
        errors["depth"] = "Permission group depth cannot exceed 5."
    return errors
