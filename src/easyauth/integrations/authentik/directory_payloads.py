from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

type DirectoryJson = dict[str, JsonValue]
type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]

INVALID_MANAGED_USERS_FIELD_TYPE = "invalid managed users field type"
EMPTY_MANAGED_USERS_FIELD = "empty managed users field"
MISSING_DIRECTORY_IDENTITY_FIELD = "missing directory identity field"
UNSUPPORTED_DIRECTORY_USER_STATUS = "unsupported directory user status"
UNSUPPORTED_RESOLVED_AT = "managed users resolved_at must be a timezone-aware ISO datetime"
INVALID_DIRECTORY_COLLECTION = "directory response results must be a list"


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
    avatar: str
    title: str
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


@dataclass(frozen=True, slots=True)
class DingTalkManagedUser:
    source_user_id: str
    authentik_user_id: str
    authentik_user_active: bool
    directory_active: bool
    is_deleted: bool


@dataclass(frozen=True, slots=True)
class DingTalkManagedUsers:
    source_slug: str
    corp_id: str
    manager_user_id: str
    resolver: str
    stale: bool
    resolved_at: str
    users: tuple[DingTalkManagedUser, ...]
    active_authentik_user_ids: tuple[str, ...]


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
    # 身份键缺失必须报错; 用 "" 兜底会让所有部门坍缩成同一行垃圾镜像。
    return DingTalkDirectoryDepartment(
        source_slug=_string(payload.get("source_slug")) or source_slug,
        corp_id=_required_identity(payload, "corp_id"),
        dept_id=_required_identity(payload, "dept_id"),
        parent_id=_string(payload.get("parent_id")) or _string(payload.get("parent_dept_id")),
        name=_string(payload.get("name")),
        order=_int(payload.get("order")),
    )


def parse_users(payload: DirectoryJson, *, source_slug: str) -> tuple[DingTalkDirectoryUser, ...]:
    return tuple(parse_user(item, source_slug=source_slug) for item in _items(payload))


def parse_user(payload: DirectoryJson, *, source_slug: str) -> DingTalkDirectoryUser:
    # 身份键缺失必须报错; 字段改名时全量用户被解析成 user_id="" 会坍缩成一行垃圾镜像,
    # 任务却报出健康的 user_count。
    return DingTalkDirectoryUser(
        source_slug=_string(payload.get("source_slug")) or source_slug,
        corp_id=_required_identity(payload, "corp_id"),
        user_id=_required_identity(payload, "user_id"),
        union_id=_string(payload.get("union_id")),
        name=_string(payload.get("name")),
        avatar=_string(payload.get("avatar")),
        title=_string(payload.get("title")),
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


def parse_managed_users(payload: DirectoryJson, *, source_slug: str) -> DingTalkManagedUsers:
    parsed_users = tuple(
        _parse_managed_user(_safe_mapping(item)) for item in _required_list(payload, "users")
    )
    return DingTalkManagedUsers(
        source_slug=_required_string(payload, "source_slug") or source_slug,
        corp_id=_required_string(payload, "corp_id"),
        manager_user_id=_required_string(payload, "manager_user_id"),
        resolver=_string(payload.get("resolver")),
        stale=payload.get("stale") is True,
        resolved_at=_required_aware_datetime_string(payload, "resolved_at"),
        users=parsed_users,
        active_authentik_user_ids=tuple(
            user.authentik_user_id for user in parsed_users if _is_active_linked_user(user)
        ),
    )


def _parse_managed_user(payload: DirectoryJson) -> DingTalkManagedUser:
    return DingTalkManagedUser(
        source_user_id=_required_string(payload, "source_user_id"),
        authentik_user_id=_required_string(payload, "authentik_user_id", allow_empty=True),
        authentik_user_active=_required_bool(payload, "authentik_user_active"),
        directory_active=_required_bool(payload, "directory_active"),
        is_deleted=_required_bool(payload, "is_deleted"),
    )


def _is_active_linked_user(user: DingTalkManagedUser) -> bool:
    return (
        user.authentik_user_id != ""
        and user.authentik_user_active
        and user.directory_active
        and not user.is_deleted
    )


def _items(payload: DirectoryJson) -> tuple[DirectoryJson, ...]:
    results = payload.get("results")
    if not isinstance(results, list):
        # 缺失/错型集合与权威空集不是一回事; 只有显式 results=[] 才表示本页为空。
        raise TypeError(INVALID_DIRECTORY_COLLECTION)
    return tuple(_safe_mapping(item) for item in results)


def _safe_mapping(value: object) -> DirectoryJson:
    return cast("DirectoryJson", value) if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return cast("list[object]", value) if isinstance(value, list) else []


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _required_string(payload: DirectoryJson, key: str, *, allow_empty: bool = False) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise TypeError(INVALID_MANAGED_USERS_FIELD_TYPE)
    if not allow_empty and value == "":
        raise ValueError(EMPTY_MANAGED_USERS_FIELD)
    return value


def _required_bool(payload: DirectoryJson, key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise TypeError(INVALID_MANAGED_USERS_FIELD_TYPE)
    return value


def _required_list(payload: DirectoryJson, key: str) -> list[object]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise TypeError(INVALID_MANAGED_USERS_FIELD_TYPE)
    return cast("list[object]", value)


def _required_aware_datetime_string(payload: DirectoryJson, key: str) -> str:
    # 在数据入口就把 resolved_at 校验为带时区的 ISO datetime, 否则错误会一路透传到
    # 响应序列化器让整个权限查询 500(并连累无关 grant)。此处抛 ValueError,
    # 由 get_managed_users 归为目录不可用 -> 503 依赖故障(BF-3)。
    value = _required_string(payload, key)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(UNSUPPORTED_RESOLVED_AT) from error
    if parsed.tzinfo is None:
        raise ValueError(UNSUPPORTED_RESOLVED_AT)
    return value


def _required_identity(payload: DirectoryJson, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or value == "":
        message = f"{MISSING_DIRECTORY_IDENTITY_FIELD}: {key}"
        raise ValueError(message)
    return value


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
    raise ValueError(UNSUPPORTED_DIRECTORY_USER_STATUS)
