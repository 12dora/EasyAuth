from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final, cast

from django.db import transaction
from django.db.models import Count

from easyauth.accounts.models import (
    DingTalkDepartmentMirror,
    DingTalkDirectorySyncState,
    DingTalkUserMirror,
)
from easyauth.grants.department_reconcile import schedule_department_grant_reconcile
from easyauth.integrations.authentik.directory_client import AuthentikDirectoryUnavailableError
from easyauth.integrations.authentik.directory_contract import directory_user_key
from easyauth.integrations.authentik.directory_sync_mirror import (
    _sync_user_mirror_avatars,
    _update_user_mirror_summary,
    _upsert_department,
    _upsert_org_context,
    _upsert_user,
)
from easyauth.integrations.authentik.directory_sync_reconciliation import (
    _reconcile_missing_rows,
    _reconcile_user_mirror_status,
)
from easyauth.integrations.authentik.directory_sync_snapshot import (
    _complete_directory_snapshot,
    _keys_for_corps,
    _list,
    _mapping,
    _object_corp_id,
    _org_contexts_for_corps,
    _payloads_for_corps,
    _read_directory_status,
    _status_only_snapshot,
    _string,
)
from easyauth.integrations.authentik.directory_sync_types import (
    AuthentikDirectorySyncClient,
    AuthentikDirectorySyncResult,
    UnsupportedDirectoryStatusError,
    _DirectorySnapshot,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.db.models import Model, QuerySet

    from easyauth.integrations.authentik.directory_contract import CorpSnapshotContract
    from easyauth.integrations.authentik.directory_payloads import DirectoryJson

logger = logging.getLogger(__name__)

DIRECTORY_STALE_GENERATION_MESSAGE: Final = "钉钉目录旧 generation 已被 fencing 拒绝。"

__all__ = [
    "AuthentikDirectorySyncClient",
    "AuthentikDirectorySyncResult",
    "UnsupportedDirectoryStatusError",
    "sync_authentik_dingtalk_directory",
]


def sync_authentik_dingtalk_directory(
    client: AuthentikDirectorySyncClient,
) -> AuthentikDirectorySyncResult:
    # 先读一次 status。status_contract 已要求每 corp 为 success 终态。
    # 全 corp generation 未变且本地活镜像人口与契约计数一致时, 不拉部门/用户/
    # 组织上下文, 只刷新新鲜度。任一 corp 需要写入(世代前进, 或镜像与契约计数
    # 不一致的修复)时再拉完整快照, 并做拉取前后 status 一致性校验。
    status, source_slug, contracts = _read_directory_status(client)
    status_snapshot = _status_only_snapshot(
        status=status,
        source_slug=source_slug,
        contracts=contracts,
    )
    unchanged = _apply_unchanged_directory(status_snapshot)
    if unchanged is not None:
        return unchanged
    snapshot = _complete_directory_snapshot(
        client,
        source_slug=source_slug,
        contracts=contracts,
    )
    return _apply_directory_snapshot(snapshot)


def _apply_unchanged_directory(
    snapshot: _DirectorySnapshot,
) -> AuthentikDirectorySyncResult | None:
    with transaction.atomic():
        states = _existing_locked_sync_states(snapshot)
        applied = {
            corp_id: states[corp_id].generation if corp_id in states else -1
            for corp_id in snapshot.contracts
        }
        writable_corp_ids, confirmed_corp_ids = _classify_corp_ids(snapshot, applied)
        if writable_corp_ids:
            return None
        result = _unchanged_sync_result(confirmed_corp_ids)
        _refresh_confirmed_sync_states(snapshot, states, confirmed_corp_ids)
        schedule_department_grant_reconcile(trigger="directory-sync")
        return result


def _apply_directory_snapshot(
    snapshot: _DirectorySnapshot,
) -> AuthentikDirectorySyncResult:
    # 同一 source/corp 的状态行既是数据库串行点, 也是持久 generation fence。
    # 整轮写入使用同一事务: 任何落库/撤权/生命周期异常都会整体回滚。
    # 上游 generation 未变但镜像人口与契约计数不一致时仍走写入修复, 把缺失行
    # 补回、把多余部门剪掉。确认未变的 corp 只刷新 last_synced_at: 新鲜度表示
    # "已在本时刻核对镜像", 而不是"上游上次发生变化的时间"。
    with transaction.atomic():
        locked_states = _lock_sync_states(snapshot)
        writable_corp_ids, confirmed_corp_ids = _classify_corp_ids(
            snapshot,
            {corp_id: state.generation for corp_id, state in locked_states.items()},
        )
        if writable_corp_ids:
            result = _write_writable_directory_snapshot(
                snapshot,
                locked_states,
                writable_corp_ids=writable_corp_ids,
                confirmed_corp_ids=confirmed_corp_ids,
            )
        else:
            result = _unchanged_sync_result(confirmed_corp_ids)
        _refresh_confirmed_sync_states(snapshot, locked_states, confirmed_corp_ids)
        schedule_department_grant_reconcile(trigger="directory-sync")
        return result


def _unchanged_sync_result(confirmed_corp_ids: frozenset[str]) -> AuthentikDirectorySyncResult:
    return AuthentikDirectorySyncResult(
        department_count=0,
        user_count=0,
        org_context_count=0,
        sync_state_count=0,
        confirmed_corp_count=len(confirmed_corp_ids),
    )


def _write_writable_directory_snapshot(
    snapshot: _DirectorySnapshot,
    locked_states: dict[str, DingTalkDirectorySyncState],
    *,
    writable_corp_ids: frozenset[str],
    confirmed_corp_ids: frozenset[str],
) -> AuthentikDirectorySyncResult:
    writable_snapshot = _snapshot_for_corps(snapshot, writable_corp_ids)
    for department in writable_snapshot.departments:
        _upsert_department(department)
    org_context_count = 0
    for user_payload in writable_snapshot.users:
        corp_id = _string(user_payload.get("corp_id"))
        _upsert_user(
            user_payload,
            generation=writable_snapshot.contracts[corp_id].generation,
        )
        org_context = writable_snapshot.org_contexts.get(directory_user_key(user_payload))
        if org_context is not None:
            _upsert_org_context(org_context)
            _update_user_mirror_summary(org_context)
            org_context_count += 1
    _sync_user_mirror_avatars(writable_snapshot.users)
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
        offboarding_deferred_count=reconciliation.offboarding_deferred_count,
        confirmed_corp_count=len(confirmed_corp_ids),
    )


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


def _existing_locked_sync_states(
    snapshot: _DirectorySnapshot,
) -> dict[str, DingTalkDirectorySyncState]:
    rows = (
        DingTalkDirectorySyncState.objects.select_for_update()
        .filter(
            source_slug=snapshot.source_slug,
            corp_id__in=tuple(snapshot.contracts),
        )
        .order_by("corp_id")
    )
    return {state.corp_id: state for state in rows}


def _classify_corp_ids(
    snapshot: _DirectorySnapshot,
    applied_generations: dict[str, int],
) -> tuple[frozenset[str], frozenset[str]]:
    writable: set[str] = set()
    confirmed: set[str] = set()
    live_counts = _live_mirror_counts(
        snapshot,
        _equal_generation_corp_ids(snapshot, applied_generations),
    )
    for corp_id, contract in snapshot.contracts.items():
        applied_generation = applied_generations[corp_id]
        if contract.generation < applied_generation:
            message = (
                f"{DIRECTORY_STALE_GENERATION_MESSAGE}: corp={corp_id} "
                f"incoming={contract.generation} applied={applied_generation}"
            )
            raise AuthentikDirectoryUnavailableError(message)
        if _corp_needs_directory_write(
            contract,
            applied_generation=applied_generation,
            live_count=live_counts.get(corp_id),
        ):
            writable.add(corp_id)
            continue
        confirmed.add(corp_id)
    return frozenset(writable), frozenset(confirmed)


def _corp_needs_directory_write(
    contract: CorpSnapshotContract,
    *,
    applied_generation: int,
    live_count: tuple[int, int] | None,
) -> bool:
    if contract.generation > applied_generation:
        return True
    # generation 未变但活镜像人口与契约不一致: 走与世代前进相同的写入路径修复。
    return live_count != (contract.user_count, contract.department_count)


def _equal_generation_corp_ids(
    snapshot: _DirectorySnapshot,
    applied_generations: dict[str, int],
) -> frozenset[str]:
    return frozenset(
        corp_id
        for corp_id, contract in snapshot.contracts.items()
        if applied_generations[corp_id] == contract.generation
    )


def _live_mirror_counts(
    snapshot: _DirectorySnapshot,
    corp_ids: frozenset[str],
) -> dict[str, tuple[int, int]]:
    if not corp_ids:
        return {}
    # 活镜像人口必须与 status 契约 counters 一致, 否则 generation 未变也要写入修复。
    # 用户只计非 tombstone: 全量 apply 把快照内用户 upsert 为 is_tombstone=False
    # (含快照内 departed), 快照外用户保留 tombstone, 不计入契约 user_count。
    # 部门无 tombstone, 缺失即物理删除, 因此计该 (source_slug, corp_id) 的全部部门行。
    corp_id_tuple = tuple(corp_ids)
    user_counts = _corp_id_counts(
        DingTalkUserMirror.objects.filter(
            source_slug=snapshot.source_slug,
            corp_id__in=corp_id_tuple,
            is_tombstone=False,
        ),
    )
    department_counts = _corp_id_counts(
        DingTalkDepartmentMirror.objects.filter(
            source_slug=snapshot.source_slug,
            corp_id__in=corp_id_tuple,
        ),
    )
    return {
        corp_id: (user_counts.get(corp_id, 0), department_counts.get(corp_id, 0))
        for corp_id in corp_ids
    }


def _corp_id_counts(queryset: object) -> dict[str, int]:
    grouped = cast("QuerySet[Model]", queryset)
    rows = cast(
        "Iterable[tuple[str, int]]",
        grouped.values("corp_id").annotate(n=Count("id")).values_list("corp_id", "n"),
    )
    return dict(rows)


def _snapshot_for_corps(
    snapshot: _DirectorySnapshot,
    corp_ids: frozenset[str],
) -> _DirectorySnapshot:
    sync_items = [
        item for item in _list(snapshot.status.get("sync")) if _object_corp_id(item) in corp_ids
    ]
    return _DirectorySnapshot(
        source_slug=snapshot.source_slug,
        status=cast(
            "DirectoryJson",
            {"source_slug": snapshot.source_slug, "sync": sync_items},
        ),
        contracts={corp_id: snapshot.contracts[corp_id] for corp_id in corp_ids},
        departments=_payloads_for_corps(snapshot.departments, corp_ids),
        users=_payloads_for_corps(snapshot.users, corp_ids),
        org_contexts=_org_contexts_for_corps(snapshot.org_contexts, corp_ids),
        org_fetch_failures=_keys_for_corps(snapshot.org_fetch_failures, corp_ids),
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


def _refresh_confirmed_sync_states(
    snapshot: _DirectorySnapshot,
    states: dict[str, DingTalkDirectorySyncState],
    confirmed_corp_ids: frozenset[str],
) -> None:
    if not confirmed_corp_ids:
        return
    for corp_id in sorted(confirmed_corp_ids):
        state = states[corp_id]
        # 只刷新本地新鲜度。finished_at 进入 snapshot_at, 是 snapshot_id 的组成;
        # 世代未变时改写它会让分页中途 409 snapshot_mismatch。
        state.save(update_fields=["last_synced_at"])
        logger.info(
            "目录快照未变化, 已刷新新鲜度 corp=%s generation=%s",
            corp_id,
            snapshot.contracts[corp_id].generation,
        )
