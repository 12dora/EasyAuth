from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils import timezone

from easyauth.accounts.models import (
    USER_STATUS_DEPARTED,
    DingTalkDepartmentMirror,
    DingTalkUserMirror,
    DingTalkUserOrgContext,
    UserMirror,
)
from easyauth.accounts.org_context import parse_org_context
from easyauth.integrations.authentik.directory_sync_snapshot import (
    _directory_source_slug,
    _directory_user_status,
    _int,
    _list,
    _mapping,
    _string,
)

if TYPE_CHECKING:
    from easyauth.accounts.org_context import DingTalkOrgSummary
    from easyauth.integrations.authentik.directory_payloads import DirectoryJson

__all__ = [
    "_update_user_mirror_summary",
    "_upsert_department",
    "_upsert_org_context",
    "_upsert_user",
]


def _upsert_department(payload: DirectoryJson) -> None:
    source_slug = _directory_source_slug(payload)
    _ = DingTalkDepartmentMirror.objects.update_or_create(
        source_slug=source_slug,
        corp_id=_string(payload.get("corp_id")),
        dept_id=_string(payload.get("dept_id")),
        defaults={
            "parent_id": _string(payload.get("parent_id")),
            "name": _string(payload.get("name")),
            "order": _int(payload.get("order")),
        },
    )


def _upsert_user(payload: DirectoryJson, *, generation: int) -> None:
    source_slug = _directory_source_slug(payload)
    corp_id = _string(payload.get("corp_id"))
    user_id = _string(payload.get("user_id"))
    status = _directory_user_status(payload)
    existing_departed_at = (
        DingTalkUserMirror.objects.filter(
            source_slug=source_slug,
            corp_id=corp_id,
            user_id=user_id,
        )
        .values_list("departed_at", flat=True)
        .first()
    )
    departed_at = existing_departed_at or timezone.now() if status == USER_STATUS_DEPARTED else None
    _ = DingTalkUserMirror.objects.update_or_create(
        source_slug=source_slug,
        corp_id=corp_id,
        user_id=user_id,
        defaults={
            "union_id": _string(payload.get("union_id")),
            "name": _string(payload.get("name")),
            "avatar": _string(payload.get("avatar")),
            "title": _string(payload.get("title")),
            "email": _string(payload.get("email")),
            "mobile": _string(payload.get("mobile")),
            "employee_number": _string(payload.get("employee_number")),
            "department_ids": [_string(item) for item in _list(payload.get("department_ids"))],
            "manager_userid": _string(payload.get("manager_userid")),
            "status": status,
            "is_tombstone": False,
            "last_seen_generation": generation,
            "departed_at": departed_at,
        },
    )
    _backfill_user_mirror_avatar(payload)


def _backfill_user_mirror_avatar(payload: DirectoryJson) -> None:
    avatar = _string(payload.get("avatar"))
    source_slug = _directory_source_slug(payload)
    corp_id = _string(payload.get("corp_id"))
    user_id = _string(payload.get("user_id"))
    if avatar == "" or source_slug == "" or corp_id == "" or user_id == "":
        return
    # 只在 avatar_url 为空时回填目录头像, 不覆盖 OIDC 登录写入的值。
    queryset = UserMirror.objects.filter(
        dingtalk_source_slug=source_slug,
        dingtalk_corp_id=corp_id,
        dingtalk_userid=user_id,
        avatar_url="",
    )
    for user in queryset.select_for_update():
        user.avatar_url = avatar
        user.full_clean()
        user.save(update_fields=["avatar_url", "updated_at"])


def _upsert_org_context(payload: DirectoryJson) -> None:
    source_slug = _directory_source_slug(payload)
    _ = DingTalkUserOrgContext.objects.update_or_create(
        source_slug=source_slug,
        corp_id=_string(payload.get("corp_id")),
        user_id=_string(payload.get("user_id")),
        defaults={
            "departments": [_mapping(item) for item in _list(payload.get("departments"))],
            "manager": _mapping(payload.get("manager")),
            "manager_chain": [_mapping(item) for item in _list(payload.get("manager_chain"))],
            "stale": payload.get("stale") is True,
        },
    )


def _update_user_mirror_summary(payload: DirectoryJson) -> None:
    summary = _parse_summary_context(payload)
    if summary is None:
        return
    for user in _lock_summary_mirror(summary):
        previous_department = user.department
        update_fields = _apply_summary_fields(user, summary)
        _mark_department_changed(
            user,
            update_fields,
            previous_department=previous_department,
        )
        if update_fields:
            update_fields.append("updated_at")
            user.full_clean()
            user.save(update_fields=update_fields)


def _parse_summary_context(payload: DirectoryJson) -> DingTalkOrgSummary | None:
    source_slug = _directory_source_slug(payload)
    corp_id = _string(payload.get("corp_id"))
    user_id = _string(payload.get("user_id"))
    if source_slug == "" or corp_id == "" or user_id == "":
        return None
    if payload.get("stale") is True:
        # 过期快照不可信, 不用它清空或改写主管链。
        return None
    return parse_org_context(payload)


def _lock_summary_mirror(summary: DingTalkOrgSummary) -> list[UserMirror]:
    # 按 source/corp_id/userid 锁定, 与原先逐行 select_for_update 口径一致。
    return list(
        UserMirror.objects.filter(
            dingtalk_source_slug=summary.source_slug,
            dingtalk_corp_id=summary.corp_id,
            dingtalk_userid=summary.user_id,
        ).select_for_update(),
    )


def _apply_summary_fields(user: UserMirror, summary: DingTalkOrgSummary) -> list[str]:
    # 上游清空 manager/department 时必须同步清空, 否则审批路由会继续指向前任主管。
    changed = {
        "department": summary.primary_department_name,
        "manager_userid": summary.manager_user_id,
    }
    update_fields: list[str] = []
    for field, value in changed.items():
        if getattr(user, field) != value:
            setattr(user, field, value)
            update_fields.append(field)
    return update_fields


def _mark_department_changed(
    user: UserMirror,
    update_fields: list[str],
    *,
    previous_department: str,
) -> None:
    if "department" in update_fields and previous_department != "":
        # 部门变更只做提示线索(转岗是人事决策, 系统不猜, 不自动建单)。
        # 首次同步"空 → 有部门"是补数据不是转岗, 不置位, 否则全员误报"部门已变更"。
        user.department_changed_at = timezone.now()
        update_fields.append("department_changed_at")
