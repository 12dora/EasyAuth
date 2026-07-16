from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from django.db.models import Q

from easyauth.accounts.directory_references import (
    build_department_ref,
    build_dingtalk_user_ref,
)
from easyauth.accounts.models import DingTalkDepartmentMirror, DingTalkUserMirror, UserMirror

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

DINGTALK_STATUS_ACTIVE: Final = "active"


def is_directory_active(status: str) -> bool:
    return status == DINGTALK_STATUS_ACTIVE


def user_list_item(
    *,
    dingtalk_user: DingTalkUserMirror,
    authentik_user_id: str | None,
    departments: list[JsonValue],
) -> dict[str, JsonValue]:
    return {
        "user_id": authentik_user_id,
        "dingtalk_user_id": dingtalk_user.user_id,
        "source_slug": dingtalk_user.source_slug,
        "corp_id": dingtalk_user.corp_id,
        "user_ref": build_dingtalk_user_ref(
            source_slug=dingtalk_user.source_slug,
            corp_id=dingtalk_user.corp_id,
            user_id=dingtalk_user.user_id,
        ),
        "name": dingtalk_user.name,
        "avatar_url": dingtalk_user.avatar or "",
        "title": dingtalk_user.title or "",
        "email": dingtalk_user.email,
        "mobile": dingtalk_user.mobile,
        "employee_number": dingtalk_user.employee_number,
        "status": dingtalk_user.status,
        "departments": departments,
        "active": is_directory_active(dingtalk_user.status),
    }


def manager_summary_item(
    *,
    dingtalk_user: DingTalkUserMirror,
    authentik_user_id: str | None,
) -> dict[str, JsonValue]:
    return {
        "user_id": authentik_user_id,
        "dingtalk_user_id": dingtalk_user.user_id,
        "source_slug": dingtalk_user.source_slug,
        "corp_id": dingtalk_user.corp_id,
        "user_ref": build_dingtalk_user_ref(
            source_slug=dingtalk_user.source_slug,
            corp_id=dingtalk_user.corp_id,
            user_id=dingtalk_user.user_id,
        ),
        "name": dingtalk_user.name,
        "title": dingtalk_user.title or "",
        "email": dingtalk_user.email,
        "mobile": dingtalk_user.mobile,
        "employee_number": dingtalk_user.employee_number,
        "status": dingtalk_user.status,
        "active": is_directory_active(dingtalk_user.status),
    }


def removed_directory_user_item(user: UserMirror) -> dict[str, JsonValue]:
    # 曾 SSO 登录但仍从钉钉目录移除: 详情可查, 标记 inactive 且无部门/主管。
    empty_departments: list[JsonValue] = []
    return {
        "user_id": user.authentik_user_id,
        "dingtalk_user_id": user.dingtalk_userid,
        "source_slug": "",
        "corp_id": user.dingtalk_corp_id,
        "user_ref": f"dt:{user.dingtalk_userid}",
        "name": user.name,
        "avatar_url": user.avatar_url or "",
        "title": "",
        "email": user.email,
        "mobile": "",
        "employee_number": user.employee_number,
        "status": "departed",
        "departments": empty_departments,
        "active": False,
        "manager": None,
    }


def department_item(department: DingTalkDepartmentMirror) -> dict[str, JsonValue]:
    return {
        "department_id": department.dept_id,
        "source_slug": department.source_slug,
        "corp_id": department.corp_id,
        "department_ref": build_department_ref(
            source_slug=department.source_slug,
            corp_id=department.corp_id,
            department_id=department.dept_id,
        ),
        "parent_id": department.parent_id,
        "name": department.name,
        "order": department.order,
    }


def department_ids_sorted(raw_ids: list[str] | None) -> list[str]:
    if not raw_ids:
        return []
    return sorted({str(item) for item in raw_ids if str(item)})


def build_departments_payload(
    *,
    department_ids: list[str],
    names_by_key: dict[tuple[str, str, str], str],
    source_slug: str,
    corp_id: str,
) -> list[JsonValue]:
    items: list[JsonValue] = []
    for dept_id in department_ids_sorted(department_ids):
        item: dict[str, JsonValue] = {
            "department_id": dept_id,
            "source_slug": source_slug,
            "corp_id": corp_id,
            "department_ref": build_department_ref(
                source_slug=source_slug,
                corp_id=corp_id,
                department_id=dept_id,
            ),
            "name": names_by_key.get((source_slug, corp_id, dept_id), ""),
        }
        items.append(item)
    return items


def load_department_names(
    *,
    source_slugs: set[str],
    corp_ids: set[str],
    department_ids: set[str],
) -> dict[tuple[str, str, str], str]:
    if not source_slugs or not corp_ids or not department_ids:
        return {}
    rows = cast(
        "list[tuple[str, str, str, str]]",
        list(
            DingTalkDepartmentMirror.objects.filter(
                source_slug__in=source_slugs,
                corp_id__in=corp_ids,
                dept_id__in=department_ids,
            ).values_list("source_slug", "corp_id", "dept_id", "name"),
        ),
    )
    return {(source_slug, corp_id, dept_id): name for source_slug, corp_id, dept_id, name in rows}


def load_authentik_ids_by_dingtalk(
    pairs: set[tuple[str, str, str]],
) -> dict[tuple[str, str, str], str]:
    """(source_slug, corp_id, dingtalk_userid) → authentik_user_id。"""
    if not pairs:
        return {}
    query = Q()
    for _source_slug, corp_id, dingtalk_userid in pairs:
        query |= Q(dingtalk_corp_id=corp_id, dingtalk_userid=dingtalk_userid)
    rows = cast(
        "list[tuple[str, str, str]]",
        list(
            UserMirror.objects.filter(query).values_list(
                "dingtalk_corp_id",
                "dingtalk_userid",
                "authentik_user_id",
            ),
        ),
    )
    ids_by_corp_user: dict[tuple[str, str], str] = {}
    duplicates: set[tuple[str, str]] = set()
    for corp_id, dingtalk_userid, authentik_user_id in rows:
        key = (corp_id, dingtalk_userid)
        if key in ids_by_corp_user:
            duplicates.add(key)
        else:
            ids_by_corp_user[key] = authentik_user_id
    return {
        (source_slug, corp_id, dingtalk_userid): ids_by_corp_user[(corp_id, dingtalk_userid)]
        for source_slug, corp_id, dingtalk_userid in pairs
        if (corp_id, dingtalk_userid) in ids_by_corp_user
        and (corp_id, dingtalk_userid) not in duplicates
    }


def build_user_list_items(
    dingtalk_users: list[DingTalkUserMirror],
) -> list[JsonValue]:
    pairs = {(row.source_slug, row.corp_id, row.user_id) for row in dingtalk_users}
    authentik_ids = load_authentik_ids_by_dingtalk(pairs)
    department_ids: set[str] = set()
    source_slugs: set[str] = set()
    corp_ids: set[str] = set()
    for row in dingtalk_users:
        source_slugs.add(row.source_slug)
        corp_ids.add(row.corp_id)
        department_ids.update(department_ids_sorted(row.department_ids))
    names = load_department_names(
        source_slugs=source_slugs,
        corp_ids=corp_ids,
        department_ids=department_ids,
    )
    return [
        user_list_item(
            dingtalk_user=row,
            authentik_user_id=authentik_ids.get((row.source_slug, row.corp_id, row.user_id)),
            departments=build_departments_payload(
                department_ids=list(row.department_ids or []),
                names_by_key=names,
                source_slug=row.source_slug,
                corp_id=row.corp_id,
            ),
        )
        for row in dingtalk_users
    ]


def build_user_detail(
    dingtalk_user: DingTalkUserMirror,
) -> dict[str, JsonValue]:
    # build_user_list_items 恒返回 dict 条目。
    detail = dict(cast("dict[str, JsonValue]", build_user_list_items([dingtalk_user])[0]))
    manager_userid = (dingtalk_user.manager_userid or "").strip()
    if not manager_userid:
        detail["manager"] = None
        return detail
    manager = (
        DingTalkUserMirror.objects.filter(
            source_slug=dingtalk_user.source_slug,
            corp_id=dingtalk_user.corp_id,
            user_id=manager_userid,
        )
        .order_by("source_slug")
        .first()
    )
    if manager is None:
        detail["manager"] = None
        return detail
    authentik_ids = load_authentik_ids_by_dingtalk(
        {(manager.source_slug, manager.corp_id, manager.user_id)},
    )
    detail["manager"] = manager_summary_item(
        dingtalk_user=manager,
        authentik_user_id=authentik_ids.get(
            (manager.source_slug, manager.corp_id, manager.user_id),
        ),
    )
    return detail


def build_manager_full_item(manager: DingTalkUserMirror) -> dict[str, JsonValue]:
    return dict(cast("dict[str, JsonValue]", build_user_list_items([manager])[0]))
