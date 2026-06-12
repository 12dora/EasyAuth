from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, is_dataclass
from typing import TYPE_CHECKING, Protocol, cast

from django.db import transaction

from easyauth.accounts.models import (
    DingTalkDepartmentMirror,
    DingTalkDirectorySyncState,
    DingTalkUserMirror,
    DingTalkUserOrgContext,
    UserMirror,
)
from easyauth.accounts.org_context import parse_org_context

if TYPE_CHECKING:
    from easyauth.integrations.authentik.directory_payloads import DirectoryJson


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


def sync_authentik_dingtalk_directory(
    client: AuthentikDirectorySyncClient,
) -> AuthentikDirectorySyncResult:
    with transaction.atomic():
        sync_state_count = _sync_status(client.get_status())
        department_count = 0
        for department in _iter_objects(client.iter_departments()):
            _upsert_department(_mapping(department))
            department_count += 1

        user_count = 0
        org_context_count = 0
        for user in _iter_objects(client.iter_users()):
            user_payload = _mapping(user)
            _upsert_user(user_payload)
            user_count += 1
            corp_id = _string(user_payload.get("corp_id"))
            user_id = _string(user_payload.get("user_id"))
            if corp_id and user_id:
                org_context = _mapping(client.get_user_org(corp_id, user_id))
                _upsert_org_context(org_context)
                _update_user_mirror_summary(org_context)
                org_context_count += 1
    return AuthentikDirectorySyncResult(
        department_count=department_count,
        user_count=user_count,
        org_context_count=org_context_count,
        sync_state_count=sync_state_count,
    )


def _sync_status(status: object) -> int:
    payload = _mapping(status)
    source_slug = _string(payload.get("source_slug")) or "dingtalk"
    count = 0
    for item in _list(payload.get("sync")):
        sync = _mapping(item)
        corp_id = _string(sync.get("corp_id"))
        if corp_id == "":
            continue
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
    summary = parse_org_context(payload)
    changed = {
        "department": summary.primary_department_name,
        "manager_userid": summary.manager_user_id,
    }
    if not any(changed.values()):
        return
    queryset = UserMirror.objects.filter(dingtalk_corp_id=corp_id, dingtalk_userid=user_id)
    for user in queryset.select_for_update():
        update_fields: list[str] = []
        for field, value in changed.items():
            if value and getattr(user, field) != value:
                setattr(user, field, value)
                update_fields.append(field)
        if update_fields:
            update_fields.append("updated_at")
            user.full_clean()
            user.save(update_fields=update_fields)


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
