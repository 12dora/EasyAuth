from __future__ import annotations

from dataclasses import dataclass
from typing import cast

type DirectoryJson = dict[str, JsonValue]
type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class DingTalkDirectoryStatus:
    source_slug: str
    sync: tuple[DirectoryJson, ...]


@dataclass(frozen=True, slots=True)
class DingTalkDirectoryDepartment:
    source_slug: str
    corp_id: str
    dept_id: str
    parent_id: str
    name: str
    order: int


@dataclass(frozen=True, slots=True)
class DingTalkDirectoryUser:
    source_slug: str
    corp_id: str
    user_id: str
    union_id: str
    name: str
    department_ids: tuple[str, ...]
    manager_userid: str
    status: str


@dataclass(frozen=True, slots=True)
class DingTalkDirectoryOrgContext:
    source_slug: str
    corp_id: str
    user_id: str
    departments: tuple[DirectoryJson, ...]
    manager: DirectoryJson
    manager_chain: tuple[DirectoryJson, ...]
    stale: bool
    last_synced_at: str


def parse_status(payload: DirectoryJson, *, source_slug: str) -> DingTalkDirectoryStatus:
    return DingTalkDirectoryStatus(
        source_slug=_string(payload.get("source_slug")) or source_slug,
        sync=tuple(_safe_mapping(item) for item in _list(payload.get("sync"))),
    )


def parse_departments(
    payload: DirectoryJson,
    *,
    source_slug: str,
) -> tuple[DingTalkDirectoryDepartment, ...]:
    return tuple(parse_department(item, source_slug=source_slug) for item in _items(payload))


def parse_department(payload: DirectoryJson, *, source_slug: str) -> DingTalkDirectoryDepartment:
    return DingTalkDirectoryDepartment(
        source_slug=_string(payload.get("source_slug")) or source_slug,
        corp_id=_string(payload.get("corp_id")),
        dept_id=_string(payload.get("dept_id")),
        parent_id=_string(payload.get("parent_id")) or _string(payload.get("parent_dept_id")),
        name=_string(payload.get("name")),
        order=_int(payload.get("order")),
    )


def parse_users(payload: DirectoryJson, *, source_slug: str) -> tuple[DingTalkDirectoryUser, ...]:
    return tuple(parse_user(item, source_slug=source_slug) for item in _items(payload))


def parse_user(payload: DirectoryJson, *, source_slug: str) -> DingTalkDirectoryUser:
    return DingTalkDirectoryUser(
        source_slug=_string(payload.get("source_slug")) or source_slug,
        corp_id=_string(payload.get("corp_id")),
        user_id=_string(payload.get("user_id")),
        union_id=_string(payload.get("union_id")),
        name=_string(payload.get("name")),
        department_ids=tuple(
            _string(item)
            for item in (_list(payload.get("department_ids")) or _list(payload.get("dept_id_list")))
        ),
        manager_userid=_string(payload.get("manager_userid"))
        or _string(payload.get("manager_user_id")),
        status=_user_status(payload),
    )


def parse_org_context(payload: DirectoryJson, *, source_slug: str) -> DingTalkDirectoryOrgContext:
    return DingTalkDirectoryOrgContext(
        source_slug=_string(payload.get("source_slug")) or source_slug,
        corp_id=_string(payload.get("corp_id")),
        user_id=_string(payload.get("user_id")),
        departments=tuple(_safe_mapping(item) for item in _list(payload.get("departments"))),
        manager=_safe_mapping(payload.get("manager")),
        manager_chain=tuple(_safe_mapping(item) for item in _list(payload.get("manager_chain"))),
        stale=payload.get("stale") is True,
        last_synced_at=_string(payload.get("last_synced_at")),
    )


def _items(payload: DirectoryJson) -> tuple[DirectoryJson, ...]:
    if isinstance(payload.get("results"), list):
        return tuple(_safe_mapping(item) for item in _list(payload.get("results")))
    if isinstance(payload.get("items"), list):
        return tuple(_safe_mapping(item) for item in _list(payload.get("items")))
    if isinstance(payload.get("departments"), list):
        return tuple(_safe_mapping(item) for item in _list(payload.get("departments")))
    if isinstance(payload.get("users"), list):
        return tuple(_safe_mapping(item) for item in _list(payload.get("users")))
    return ()


def _safe_mapping(value: object) -> DirectoryJson:
    return cast("DirectoryJson", value) if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return cast("list[object]", value) if isinstance(value, list) else []


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _user_status(payload: DirectoryJson) -> str:
    status = _string(payload.get("status"))
    if status:
        return status
    if payload.get("is_deleted") is True:
        return "deleted"
    if payload.get("active") is False:
        return "inactive"
    if payload.get("active") is True:
        return "active"
    return ""
