from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror


@dataclass(frozen=True, slots=True)
class DingTalkOrgSummary:
    corp_id: str = ""
    user_id: str = ""
    primary_department_name: str = ""
    manager_user_id: str = ""


def apply_dingtalk_org_context(user: UserMirror, org: object) -> list[str]:
    parsed = parse_org_context(org)
    changed_fields: list[str] = []
    changed_fields.extend(_set_if_changed(user, "dingtalk_corp_id", parsed.corp_id))
    changed_fields.extend(_set_if_changed(user, "dingtalk_userid", parsed.user_id))
    changed_fields.extend(_set_if_changed(user, "department", parsed.primary_department_name))
    changed_fields.extend(_set_if_changed(user, "manager_userid", parsed.manager_user_id))
    return changed_fields


def parse_org_context(org: object) -> DingTalkOrgSummary:
    if not isinstance(org, dict):
        return DingTalkOrgSummary()
    org_mapping = cast("dict[str, object]", org)
    return DingTalkOrgSummary(
        corp_id=_string(org_mapping.get("corp_id")),
        user_id=_string(org_mapping.get("user_id")),
        primary_department_name=_primary_department_name(org_mapping.get("departments")),
        manager_user_id=_manager_user_id(org_mapping.get("manager")),
    )


def _primary_department_name(value: object) -> str:
    if not isinstance(value, list):
        return ""
    departments = cast("list[object]", value)
    for item in departments:
        if isinstance(item, dict):
            department = cast("dict[str, object]", item)
            name = _string(department.get("name"))
            if name:
                return name
    return ""


def _manager_user_id(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    manager = cast("dict[str, object]", value)
    return _string(manager.get("user_id"))


def _set_if_changed(user: UserMirror, field: str, value: str) -> list[str]:
    if value == "" or getattr(user, field) == value:
        return []
    setattr(user, field, value)
    return [field]


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""
