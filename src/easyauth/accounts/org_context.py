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
    if not isinstance(org, dict):
        # 没有组织上下文时不改写任何字段, 避免用缺失 claim 清空事实数据。
        return []
    parsed = parse_org_context(org)
    changed_fields: list[str] = []
    changed_fields.extend(_set_if_changed(user, "dingtalk_corp_id", parsed.corp_id))
    changed_fields.extend(_set_if_changed(user, "dingtalk_userid", parsed.user_id))
    # 上下文存在时 department/manager 以上游为准, 包括被清空的情况。
    changed_fields.extend(_apply_field(user, "department", parsed.primary_department_name))
    changed_fields.extend(_apply_field(user, "manager_userid", parsed.manager_user_id))
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
    # 上游返回的 departments 顺序不稳定; 若直接取"第一个", 多部门员工的首选部门会在两次同步
    # 之间抖动, 令 directory_sync._update_user_mirror_summary 误判部门变化、给根本没转岗的人
    # 置位 department_changed_at(假"转岗")。这里先按 dept_id 稳定排序再取首个有名字的部门,
    # 使同一组部门始终解析出同一个首选值, 从源头消除假转岗。
    # 注: department_changed_at 目前不在前端展示(见 item 3), 仅作后端内部线索, 但仍需修对,
    # 以免污染数据与依赖它的转岗清除逻辑。
    dept_dicts = [
        cast("dict[str, object]", item) for item in departments if isinstance(item, dict)
    ]
    dept_dicts.sort(key=lambda dept: _string(dept.get("dept_id")))
    for department in dept_dicts:
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


def _apply_field(user: UserMirror, field: str, value: str) -> list[str]:
    if getattr(user, field) == value:
        return []
    setattr(user, field, value)
    return [field]


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""
