from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from django.db import transaction

from easyauth.accounts.models import DingTalkDirectorySyncState
from easyauth.integrations.authentik.directory_client import AuthentikDirectoryUnavailableError
from easyauth.integrations.authentik.directory_contract import directory_user_key
from easyauth.integrations.authentik.directory_sync_mirror import (
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
    _fetch_directory_snapshot,
    _keys_for_corps,
    _list,
    _mapping,
    _object_corp_id,
    _org_contexts_for_corps,
    _payloads_for_corps,
    _string,
)
from easyauth.integrations.authentik.directory_sync_types import (
    AuthentikDirectorySyncClient,
    AuthentikDirectorySyncResult,
    UnsupportedDirectoryStatusError,
    _DirectorySnapshot,
)

if TYPE_CHECKING:
    from easyauth.integrations.authentik.directory_payloads import DirectoryJson

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
            org_context = writable_snapshot.org_contexts.get(directory_user_key(user_payload))
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
            offboarding_deferred_count=reconciliation.offboarding_deferred_count,
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
