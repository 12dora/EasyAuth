from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, is_dataclass
from typing import TYPE_CHECKING, Final, Protocol, cast

from django.db import transaction

from easyauth.accounts.models import (
    USER_STATUS_ACTIVE,
    USER_STATUS_DEPARTED,
    USER_STATUS_DISABLED,
    DingTalkDepartmentMirror,
    DingTalkDirectorySyncState,
    DingTalkUserMirror,
    DingTalkUserOrgContext,
    UserMirror,
)
from easyauth.accounts.org_context import parse_org_context
from easyauth.accounts.services import AuthentikSyncService

if TYPE_CHECKING:
    from easyauth.accounts.status import UserStatus
    from easyauth.integrations.authentik.directory_payloads import DirectoryJson

DIRECTORY_STATUS_TO_USER_STATUS: Final[dict[str, str]] = {
    "active": USER_STATUS_ACTIVE,
    "inactive": USER_STATUS_DISABLED,
    "disabled": USER_STATUS_DISABLED,
    "deleted": USER_STATUS_DEPARTED,
    "departed": USER_STATUS_DEPARTED,
}
UNSUPPORTED_DIRECTORY_STATUS_ERROR: Final = "钉钉目录用户状态无法识别。"


class AuthentikDirectorySyncClient(Protocol):
    def get_status(self) -> object: ...

    def iter_departments(self) -> Iterable[object]: ...

    def iter_users(self) -> Iterable[object]: ...

    def get_user_org(self, corp_id: str, user_id: str) -> object: ...


@dataclass(frozen=True, slots=True)
class AuthentikDirectorySyncResult:
    department_count: int
    user_count: int
    org_context_count: int
    sync_state_count: int
    pruned_department_count: int = 0
    pruned_user_count: int = 0
    status_applied_count: int = 0
    departed_count: int = 0
    revoked_count: int = 0


@dataclass(frozen=True, slots=True)
class _DirectorySnapshot:
    source_slug: str
    status: DirectoryJson
    departments: tuple[DirectoryJson, ...]
    users: tuple[DirectoryJson, ...]
    org_contexts: dict[tuple[str, str], DirectoryJson]


@dataclass(frozen=True, slots=True)
class _StatusReconciliation:
    applied_count: int
    departed_count: int
    revoked_count: int


def sync_authentik_dingtalk_directory(
    client: AuthentikDirectorySyncClient,
) -> AuthentikDirectorySyncResult:
    # 阶段一: 先把远端目录完整拉进内存; 任何一页失败都不落地半份镜像。
    snapshot = _fetch_directory_snapshot(client)

    # 阶段二: 小事务逐条 upsert, 不再用一个大事务锁住 UserMirror 阻塞登录。
    sync_state_count = _sync_status(snapshot.status)
    for department in snapshot.departments:
        with transaction.atomic():
            _upsert_department(department)
    org_context_count = 0
    for user_payload in snapshot.users:
        with transaction.atomic():
            _upsert_user(user_payload)
            org_context = snapshot.org_contexts.get(_directory_user_key(user_payload))
            if org_context is not None:
                _upsert_org_context(org_context)
                _update_user_mirror_summary(org_context)
                org_context_count += 1

    # 阶段三: 清理上游已不存在的镜像行, 避免"看似有效"的陈旧目录数据长存。
    pruned_department_count, pruned_user_count = _prune_missing_rows(snapshot)

    # 阶段四: 把目录状态回灌到 UserMirror, 离职/停用用户立即撤销 current 授权。
    reconciliation = _reconcile_user_mirror_status(snapshot)

    return AuthentikDirectorySyncResult(
        department_count=len(snapshot.departments),
        user_count=len(snapshot.users),
        org_context_count=org_context_count,
        sync_state_count=sync_state_count,
        pruned_department_count=pruned_department_count,
        pruned_user_count=pruned_user_count,
        status_applied_count=reconciliation.applied_count,
        departed_count=reconciliation.departed_count,
        revoked_count=reconciliation.revoked_count,
    )


def _fetch_directory_snapshot(client: AuthentikDirectorySyncClient) -> _DirectorySnapshot:
    status = _mapping(client.get_status())
    departments = tuple(_mapping(item) for item in _iter_objects(client.iter_departments()))
    users = tuple(_mapping(item) for item in _iter_objects(client.iter_users()))
    org_contexts: dict[tuple[str, str], DirectoryJson] = {}
    for user_payload in users:
        corp_id, user_id = _directory_user_key(user_payload)
        if corp_id and user_id:
            org_contexts[(corp_id, user_id)] = _mapping(client.get_user_org(corp_id, user_id))
    return _DirectorySnapshot(
        source_slug=_string(status.get("source_slug")) or "dingtalk",
        status=status,
        departments=departments,
        users=users,
        org_contexts=org_contexts,
    )


def _directory_user_key(payload: DirectoryJson) -> tuple[str, str]:
    return (_string(payload.get("corp_id")), _string(payload.get("user_id")))


def _sync_status(status: DirectoryJson) -> int:
    source_slug = _string(status.get("source_slug")) or "dingtalk"
    count = 0
    for item in _list(status.get("sync")):
        sync = _mapping(item)
        corp_id = _string(sync.get("corp_id"))
        if corp_id == "":
            continue
        with transaction.atomic():
            _ = DingTalkDirectorySyncState.objects.update_or_create(
                source_slug=source_slug,
                corp_id=corp_id,
                defaults={
                    "status": _string(sync.get("status")),
                    "counters": _mapping(sync.get("counters")),
                    "finished_at": _string(sync.get("finished_at")),
                    "error": _string(sync.get("error")),
                },
            )
        count += 1
    return count


def _upsert_department(payload: DirectoryJson) -> None:
    source_slug = _string(payload.get("source_slug")) or "dingtalk"
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


def _upsert_user(payload: DirectoryJson) -> None:
    source_slug = _string(payload.get("source_slug")) or "dingtalk"
    _ = DingTalkUserMirror.objects.update_or_create(
        source_slug=source_slug,
        corp_id=_string(payload.get("corp_id")),
        user_id=_string(payload.get("user_id")),
        defaults={
            "union_id": _string(payload.get("union_id")),
            "name": _string(payload.get("name")),
            "department_ids": [_string(item) for item in _list(payload.get("department_ids"))],
            "manager_userid": _string(payload.get("manager_userid")),
            "status": _string(payload.get("status")),
        },
    )


def _upsert_org_context(payload: DirectoryJson) -> None:
    source_slug = _string(payload.get("source_slug")) or "dingtalk"
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
    corp_id = _string(payload.get("corp_id"))
    user_id = _string(payload.get("user_id"))
    if corp_id == "" or user_id == "":
        return
    if payload.get("stale") is True:
        # 过期快照不可信, 不用它清空或改写主管链。
        return
    summary = parse_org_context(payload)
    # 上游清空 manager/department 时必须同步清空, 否则审批路由会继续指向前任主管。
    changed = {
        "department": summary.primary_department_name,
        "manager_userid": summary.manager_user_id,
    }
    queryset = UserMirror.objects.filter(dingtalk_corp_id=corp_id, dingtalk_userid=user_id)
    for user in queryset.select_for_update():
        update_fields: list[str] = []
        for field, value in changed.items():
            if getattr(user, field) != value:
                setattr(user, field, value)
                update_fields.append(field)
        if update_fields:
            update_fields.append("updated_at")
            user.full_clean()
            user.save(update_fields=update_fields)


def _prune_missing_rows(snapshot: _DirectorySnapshot) -> tuple[int, int]:
    corp_ids = _synced_corp_ids(snapshot)
    if not corp_ids:
        return (0, 0)

    seen_departments = {
        (_string(item.get("corp_id")), _string(item.get("dept_id")))
        for item in snapshot.departments
    }
    seen_users = {_directory_user_key(item) for item in snapshot.users}

    pruned_departments = 0
    for department in DingTalkDepartmentMirror.objects.filter(
        source_slug=snapshot.source_slug,
        corp_id__in=corp_ids,
    ):
        if (department.corp_id, department.dept_id) not in seen_departments:
            _ = department.delete()
            pruned_departments += 1

    pruned_users = 0
    for user in DingTalkUserMirror.objects.filter(
        source_slug=snapshot.source_slug,
        corp_id__in=corp_ids,
    ):
        if (user.corp_id, user.user_id) not in seen_users:
            _ = user.delete()
            _ = DingTalkUserOrgContext.objects.filter(
                source_slug=snapshot.source_slug,
                corp_id=user.corp_id,
                user_id=user.user_id,
            ).delete()
            pruned_users += 1
    return (pruned_departments, pruned_users)


def _reconcile_user_mirror_status(snapshot: _DirectorySnapshot) -> _StatusReconciliation:
    corp_ids = _synced_corp_ids(snapshot)
    if not corp_ids:
        return _StatusReconciliation(applied_count=0, departed_count=0, revoked_count=0)

    status_by_key = {
        _directory_user_key(payload): _directory_user_status(payload)
        for payload in snapshot.users
    }
    applied_count = 0
    departed_count = 0
    revoked_count = 0
    bound_users = UserMirror.objects.filter(dingtalk_corp_id__in=corp_ids).exclude(
        dingtalk_userid="",
    )
    for user in bound_users:
        key = (user.dingtalk_corp_id, user.dingtalk_userid)
        # 目录里已经不存在的绑定用户按离职处理, 与上游硬删除口径一致。
        target_status = status_by_key.get(key, USER_STATUS_DEPARTED)
        result = AuthentikSyncService.apply_directory_status(user, target_status)
        applied_count += 1
        revoked_count += result.revoked_count
        if result.user.status == USER_STATUS_DEPARTED:
            departed_count += 1
    return _StatusReconciliation(
        applied_count=applied_count,
        departed_count=departed_count,
        revoked_count=revoked_count,
    )


def _synced_corp_ids(snapshot: _DirectorySnapshot) -> frozenset[str]:
    # 只有本次响应里真实出现过用户的 corp 才允许 prune/离职回收,
    # 防止一次空响应把全公司授权误撤。
    return frozenset(
        corp_id for corp_id, _user_id in map(_directory_user_key, snapshot.users) if corp_id
    )


def _directory_user_status(payload: DirectoryJson) -> UserStatus:
    status_text = _string(payload.get("status"))
    mapped = DIRECTORY_STATUS_TO_USER_STATUS.get(status_text)
    if mapped is None:
        message = f"{UNSUPPORTED_DIRECTORY_STATUS_ERROR}: {status_text!r}"
        raise ValueError(message)
    return cast("UserStatus", mapped)


def _iter_objects(value: object) -> tuple[object, ...]:
    if isinstance(value, tuple):
        return cast("tuple[object, ...]", value)
    if isinstance(value, list):
        return tuple(cast("list[object]", value))
    if isinstance(value, dict | str | bytes):
        return (cast("object", value),)
    if isinstance(value, Iterable):
        return tuple(value)
    return (value,)


def _mapping(value: object) -> DirectoryJson:
    if isinstance(value, dict):
        return cast("DirectoryJson", value)
    if is_dataclass(value):
        return cast("DirectoryJson", asdict(value))  # pyright: ignore[reportArgumentType]
    return {}


def _list(value: object) -> list[object]:
    if isinstance(value, list):
        return cast("list[object]", value)
    if isinstance(value, tuple):
        return list(cast("tuple[object, ...]", value))
    return []


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0
