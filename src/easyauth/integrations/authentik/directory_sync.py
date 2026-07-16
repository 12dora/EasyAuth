from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, is_dataclass
from typing import TYPE_CHECKING, Final, Protocol, cast

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

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
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryError,
    AuthentikDirectoryUnavailableError,
)
from easyauth.lifecycle.services import start_offboarding

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
DIRECTORY_ORG_CONTEXT_UNAVAILABLE_MESSAGE: Final = "钉钉目录组织上下文全部拉取失败。"
DIRECTORY_CONTRACT_MESSAGE: Final = "钉钉目录响应不满足权威快照契约。"
DIRECTORY_GENERATION_CHANGED_MESSAGE: Final = "钉钉目录 generation 在快照拉取期间发生变化。"
DIRECTORY_STALE_GENERATION_MESSAGE: Final = "钉钉目录旧 generation 已被 fencing 拒绝。"


class UnsupportedDirectoryStatusError(AuthentikDirectoryError):
    # 未知目录状态是数据契约破坏; 归入 AuthentikDirectoryError 让同步任务重试并最终显式失败,
    # 而不是把一整轮离职回收静默跳过。
    pass


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
    tombstoned_user_count: int = 0
    status_applied_count: int = 0
    departed_count: int = 0
    revoked_count: int = 0
    org_fetch_failed_count: int = 0


@dataclass(frozen=True, slots=True)
class _CorpSnapshotContract:
    generation: int
    user_count: int
    department_count: int


@dataclass(frozen=True, slots=True)
class _DirectorySnapshot:
    source_slug: str
    status: DirectoryJson
    contracts: dict[str, _CorpSnapshotContract]
    departments: tuple[DirectoryJson, ...]
    users: tuple[DirectoryJson, ...]
    org_contexts: dict[tuple[str, str], DirectoryJson]
    org_fetch_failures: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class _StatusReconciliation:
    applied_count: int
    departed_count: int
    revoked_count: int


def sync_authentik_dingtalk_directory(
    client: AuthentikDirectorySyncClient,
) -> AuthentikDirectorySyncResult:
    # 先把远端目录完整拉进内存并验证权威快照契约; 网络请求和契约错误发生时
    # 尚未打开任何写事务, 不会留下半份镜像。
    snapshot = _fetch_directory_snapshot(client)

    # 同一 source/corp 的状态行既是数据库串行点, 也是持久 generation fence。
    # 整轮写入使用同一事务: 任何落库/撤权/生命周期异常都会整体回滚。
    with transaction.atomic():
        locked_states = _lock_sync_states(snapshot)
        writable_corp_ids = _writable_corp_ids(snapshot, locked_states)
        writable_snapshot = _snapshot_for_corps(snapshot, writable_corp_ids)
        if not writable_corp_ids:
            return AuthentikDirectorySyncResult(
                department_count=0,
                user_count=0,
                org_context_count=0,
                sync_state_count=0,
            )

        for department in writable_snapshot.departments:
            _upsert_department(department)
        org_context_count = 0
        for user_payload in writable_snapshot.users:
            corp_id = _string(user_payload.get("corp_id"))
            _upsert_user(
                user_payload,
                generation=writable_snapshot.contracts[corp_id].generation,
            )
            org_context = writable_snapshot.org_contexts.get(_directory_user_key(user_payload))
            if org_context is not None:
                _upsert_org_context(org_context)
                _update_user_mirror_summary(org_context)
                org_context_count += 1

        pruned_department_count, tombstoned_user_count = _reconcile_missing_rows(
            writable_snapshot,
        )
        reconciliation = _reconcile_user_mirror_status(writable_snapshot)
        _apply_sync_states(writable_snapshot, locked_states)

        return AuthentikDirectorySyncResult(
            department_count=len(writable_snapshot.departments),
            user_count=len(writable_snapshot.users),
            org_context_count=org_context_count,
            sync_state_count=len(writable_corp_ids),
            pruned_department_count=pruned_department_count,
            tombstoned_user_count=tombstoned_user_count,
            status_applied_count=reconciliation.applied_count,
            departed_count=reconciliation.departed_count,
            revoked_count=reconciliation.revoked_count,
            org_fetch_failed_count=len(writable_snapshot.org_fetch_failures),
        )


def _fetch_directory_snapshot(client: AuthentikDirectorySyncClient) -> _DirectorySnapshot:
    status = _mapping(client.get_status())
    source_slug, contracts = _status_contract(status)
    departments = tuple(_mapping(item) for item in _iter_objects(client.iter_departments()))
    users = tuple(_mapping(item) for item in _iter_objects(client.iter_users()))
    _assert_directory_payloads(
        source_slug=source_slug,
        contracts=contracts,
        departments=departments,
        users=users,
    )
    org_contexts: dict[tuple[str, str], DirectoryJson] = {}
    org_fetch_failures: list[tuple[str, str]] = []
    attempted = 0
    for user_payload in users:
        corp_id, user_id = _directory_user_key(user_payload)
        if not (corp_id and user_id):
            continue
        attempted += 1
        try:
            org_context = _mapping(client.get_user_org(corp_id, user_id))
            _assert_org_context(org_context, source_slug=source_slug, key=(corp_id, user_id))
            org_contexts[(corp_id, user_id)] = org_context
        except AuthentikDirectoryError:
            # 单个用户的 org 拉取失败不得中止整轮同步; 隔离该用户、聚合失败并继续。
            org_fetch_failures.append((corp_id, user_id))
    if attempted and len(org_fetch_failures) == attempted:
        # 每个用户都失败 = 上游整体故障: 必须触发重试, 而不是落地一份没有主管链的目录。
        raise AuthentikDirectoryUnavailableError(DIRECTORY_ORG_CONTEXT_UNAVAILABLE_MESSAGE)
    final_status = _mapping(client.get_status())
    final_source_slug, final_contracts = _status_contract(final_status)
    if final_source_slug != source_slug or final_contracts != contracts:
        raise AuthentikDirectoryUnavailableError(DIRECTORY_GENERATION_CHANGED_MESSAGE)
    return _DirectorySnapshot(
        source_slug=source_slug,
        status=final_status,
        contracts=contracts,
        departments=departments,
        users=users,
        org_contexts=org_contexts,
        org_fetch_failures=tuple(org_fetch_failures),
    )


def _directory_user_key(payload: DirectoryJson) -> tuple[str, str]:
    return (_string(payload.get("corp_id")), _string(payload.get("user_id")))


def _status_contract(
    status: DirectoryJson,
) -> tuple[str, dict[str, _CorpSnapshotContract]]:
    source_slug = _string(status.get("source_slug"))
    sync_items = status.get("sync")
    if source_slug == "" or not isinstance(sync_items, list | tuple) or not sync_items:
        raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)

    contracts: dict[str, _CorpSnapshotContract] = {}
    for raw_item in sync_items:
        if not isinstance(raw_item, dict):
            raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)
        sync = cast("DirectoryJson", raw_item)
        corp_id = _string(sync.get("corp_id"))
        generation = sync.get("generation")
        counters = sync.get("counters")
        if (
            corp_id == ""
            or corp_id in contracts
            or sync.get("status") != "success"
            or type(generation) is not int
            or generation < 0
            or not isinstance(counters, dict)
        ):
            raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)
        users = counters.get("users")
        departments = counters.get("departments")
        if type(users) is not int or users < 0 or type(departments) is not int or departments < 0:
            raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)
        contracts[corp_id] = _CorpSnapshotContract(
            generation=generation,
            user_count=users,
            department_count=departments,
        )
    return source_slug, contracts


def _assert_directory_payloads(
    *,
    source_slug: str,
    contracts: dict[str, _CorpSnapshotContract],
    departments: tuple[DirectoryJson, ...],
    users: tuple[DirectoryJson, ...],
) -> None:
    seen_departments: dict[str, set[str]] = {corp_id: set() for corp_id in contracts}
    for department in departments:
        corp_id = _string(department.get("corp_id"))
        dept_id = _string(department.get("dept_id"))
        item_source_slug = _string(department.get("source_slug"))
        if (
            corp_id not in contracts
            or dept_id == ""
            or (item_source_slug and item_source_slug != source_slug)
            or dept_id in seen_departments[corp_id]
        ):
            raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)
        seen_departments[corp_id].add(dept_id)

    seen_users: dict[str, set[str]] = {corp_id: set() for corp_id in contracts}
    for user in users:
        corp_id, user_id = _directory_user_key(user)
        item_source_slug = _string(user.get("source_slug"))
        if (
            corp_id not in contracts
            or user_id == ""
            or (item_source_slug and item_source_slug != source_slug)
            or user_id in seen_users[corp_id]
        ):
            raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)
        _ = _directory_user_status(user)
        seen_users[corp_id].add(user_id)

    for corp_id, contract in contracts.items():
        if (
            len(seen_users[corp_id]) != contract.user_count
            or len(seen_departments[corp_id]) != contract.department_count
        ):
            raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)


def _assert_org_context(
    payload: DirectoryJson,
    *,
    source_slug: str,
    key: tuple[str, str],
) -> None:
    item_source_slug = _string(payload.get("source_slug"))
    if (
        _directory_user_key(payload) != key
        or (item_source_slug and item_source_slug != source_slug)
        or not isinstance(payload.get("departments"), list | tuple)
        or not isinstance(payload.get("manager"), dict)
        or not isinstance(payload.get("manager_chain"), list | tuple)
        or type(payload.get("stale")) is not bool
    ):
        raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)


def _lock_sync_states(
    snapshot: _DirectorySnapshot,
) -> dict[str, DingTalkDirectorySyncState]:
    states: dict[str, DingTalkDirectorySyncState] = {}
    for corp_id in sorted(snapshot.contracts):
        _state, _created = DingTalkDirectorySyncState.objects.get_or_create(
            source_slug=snapshot.source_slug,
            corp_id=corp_id,
        )
        states[corp_id] = DingTalkDirectorySyncState.objects.select_for_update().get(
            source_slug=snapshot.source_slug,
            corp_id=corp_id,
        )
    return states


def _writable_corp_ids(
    snapshot: _DirectorySnapshot,
    states: dict[str, DingTalkDirectorySyncState],
) -> frozenset[str]:
    writable: set[str] = set()
    for corp_id, contract in snapshot.contracts.items():
        applied_generation = states[corp_id].generation
        if contract.generation < applied_generation:
            message = (
                f"{DIRECTORY_STALE_GENERATION_MESSAGE}: corp={corp_id} "
                f"incoming={contract.generation} applied={applied_generation}"
            )
            raise AuthentikDirectoryUnavailableError(message)
        if contract.generation > applied_generation:
            writable.add(corp_id)
    return frozenset(writable)


def _snapshot_for_corps(
    snapshot: _DirectorySnapshot,
    corp_ids: frozenset[str],
) -> _DirectorySnapshot:
    sync_items = [
        item
        for item in _list(snapshot.status.get("sync"))
        if _string(_mapping(item).get("corp_id")) in corp_ids
    ]
    return _DirectorySnapshot(
        source_slug=snapshot.source_slug,
        status=cast(
            "DirectoryJson",
            {"source_slug": snapshot.source_slug, "sync": sync_items},
        ),
        contracts={corp_id: snapshot.contracts[corp_id] for corp_id in corp_ids},
        departments=tuple(
            item for item in snapshot.departments if _string(item.get("corp_id")) in corp_ids
        ),
        users=tuple(item for item in snapshot.users if _string(item.get("corp_id")) in corp_ids),
        org_contexts={
            key: value for key, value in snapshot.org_contexts.items() if key[0] in corp_ids
        },
        org_fetch_failures=tuple(key for key in snapshot.org_fetch_failures if key[0] in corp_ids),
    )


def _apply_sync_states(
    snapshot: _DirectorySnapshot,
    states: dict[str, DingTalkDirectorySyncState],
) -> None:
    for item in _list(snapshot.status.get("sync")):
        sync = _mapping(item)
        corp_id = _string(sync.get("corp_id"))
        state = states[corp_id]
        state.generation = snapshot.contracts[corp_id].generation
        state.status = "success"
        state.counters = _mapping(sync.get("counters"))
        state.finished_at = _string(sync.get("finished_at"))
        state.error = _string(sync.get("error"))
        state.save(
            update_fields=[
                "generation",
                "status",
                "counters",
                "finished_at",
                "error",
                "last_synced_at",
            ],
        )


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


def _upsert_user(payload: DirectoryJson, *, generation: int) -> None:
    source_slug = _string(payload.get("source_slug")) or "dingtalk"
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
    corp_id = _string(payload.get("corp_id"))
    user_id = _string(payload.get("user_id"))
    if avatar == "" or corp_id == "" or user_id == "":
        return
    # 只在 avatar_url 为空时回填目录头像, 不覆盖 OIDC 登录写入的值。
    queryset = UserMirror.objects.filter(
        dingtalk_corp_id=corp_id,
        dingtalk_userid=user_id,
        avatar_url="",
    )
    for user in queryset.select_for_update():
        user.avatar_url = avatar
        user.full_clean()
        user.save(update_fields=["avatar_url", "updated_at"])


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
        previous_department = user.department
        for field, value in changed.items():
            if getattr(user, field) != value:
                setattr(user, field, value)
                update_fields.append(field)
        if "department" in update_fields and previous_department != "":
            # 部门变更只做提示线索(转岗是人事决策, 系统不猜, 不自动建单)。
            # 首次同步"空 → 有部门"是补数据不是转岗, 不置位, 否则全员误报"部门已变更"。
            user.department_changed_at = timezone.now()
            update_fields.append("department_changed_at")
        if update_fields:
            update_fields.append("updated_at")
            user.full_clean()
            user.save(update_fields=update_fields)


def _reconcile_missing_rows(snapshot: _DirectorySnapshot) -> tuple[int, int]:
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

    tombstoned_users = 0
    for user in DingTalkUserMirror.objects.filter(
        source_slug=snapshot.source_slug,
        corp_id__in=corp_ids,
    ):
        if (user.corp_id, user.user_id) not in seen_users:
            if not user.is_tombstone or user.status != USER_STATUS_DEPARTED:
                user.status = USER_STATUS_DEPARTED
                user.is_tombstone = True
                user.departed_at = user.departed_at or timezone.now()
                user.department_ids = []
                user.manager_userid = ""
                user.save(
                    update_fields=[
                        "status",
                        "is_tombstone",
                        "departed_at",
                        "department_ids",
                        "manager_userid",
                        "last_synced_at",
                    ],
                )
                tombstoned_users += 1
            _ = DingTalkUserOrgContext.objects.filter(
                source_slug=snapshot.source_slug,
                corp_id=user.corp_id,
                user_id=user.user_id,
            ).delete()
    return (pruned_departments, tombstoned_users)


def _reconcile_user_mirror_status(snapshot: _DirectorySnapshot) -> _StatusReconciliation:
    corp_ids = _synced_corp_ids(snapshot)
    if not corp_ids:
        return _StatusReconciliation(applied_count=0, departed_count=0, revoked_count=0)

    # 状态已在任何写入前完成契约校验, 这里仅把权威快照映射为本地域状态。
    status_by_key: dict[tuple[str, str], UserStatus] = {
        _directory_user_key(payload): _directory_user_status(payload) for payload in snapshot.users
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
        target_status = status_by_key.get(key, cast("UserStatus", USER_STATUS_DEPARTED))
        was_departed = user.status == USER_STATUS_DEPARTED
        grant_ids: tuple[int, ...] = ()
        if target_status == USER_STATUS_DEPARTED and not was_departed:
            now = timezone.now()
            effective_groups = AccessGrantGroup.objects.filter(grant_id=OuterRef("pk")).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=now),
            )
            effective_permissions = AccessGrantPermission.objects.filter(
                grant_id=OuterRef("pk"),
            ).filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=now),
            )
            grant_ids = tuple(
                AccessGrant.objects.filter(
                    user=user,
                    is_current=True,
                    status=GRANT_STATUS_ACTIVE,
                )
                .annotate(
                    has_effective_group=Exists(effective_groups),
                    has_effective_permission=Exists(effective_permissions),
                )
                .filter(Q(has_effective_group=True) | Q(has_effective_permission=True))
                .order_by("id")
                .values_list("id", flat=True),
            )
        result = AuthentikSyncService.apply_directory_status(user, target_status)
        applied_count += 1
        revoked_count += result.revoked_count
        if result.user.status == USER_STATUS_DEPARTED:
            departed_count += 1
            if not was_departed:
                # 首次检出离职: 撤权已由 apply_directory_status 完成,
                # 这里补齐生命周期立即项(自动建交接单+禁号+移出团队, §2.4)。
                _ = start_offboarding(result.user, snapshot_grant_ids=grant_ids)

    return _StatusReconciliation(
        applied_count=applied_count,
        departed_count=departed_count,
        revoked_count=revoked_count,
    )


def _synced_corp_ids(snapshot: _DirectorySnapshot) -> frozenset[str]:
    # corp 权威范围来自已验证的 success status, 而不是用户行。这样 users=0 的合法
    # 权威快照仍会清理最后一名员工; 缺失/畸形 status 已在任何写入前失败。
    return frozenset(snapshot.contracts)


def _directory_user_status(payload: DirectoryJson) -> UserStatus:
    status_text = _string(payload.get("status"))
    mapped = DIRECTORY_STATUS_TO_USER_STATUS.get(status_text)
    if mapped is None:
        message = f"{UNSUPPORTED_DIRECTORY_STATUS_ERROR}: {status_text!r}"
        raise UnsupportedDirectoryStatusError(message)
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
