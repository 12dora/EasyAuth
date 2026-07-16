from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from json import dumps
from typing import TYPE_CHECKING, cast

from django.conf import settings
from django.utils import timezone

from easyauth.accounts.models import (
    DingTalkDepartmentMirror,
    DingTalkDirectorySyncState,
    DingTalkUserMirror,
)

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue


def directory_stale_after() -> timedelta:
    seconds = cast("int", settings.EASYAUTH_DIRECTORY_STALE_AFTER_SECONDS)
    return timedelta(seconds=seconds)


def sync_state_freshness_at(state: DingTalkDirectorySyncState) -> datetime:
    # freshness 只能信任本服务在成功事务提交时写入的本地时间。finished_at 来自上游,
    # 可能受时钟漂移或错误 serializer 影响, 只能作为展示元数据。
    return state.last_synced_at


def upstream_snapshot_metadata(
    state: DingTalkDirectorySyncState,
    *,
    now: datetime,
) -> tuple[str | None, str]:
    raw_snapshot_at = state.finished_at.strip()
    if not raw_snapshot_at:
        return None, "missing"
    try:
        parsed = datetime.fromisoformat(raw_snapshot_at)
    except ValueError:
        return None, "invalid"
    if parsed.tzinfo is None:
        return None, "invalid"
    normalized = parsed.isoformat()
    if parsed > now:
        # 保留带时区的原始事实供排障, 但明确标记为 future 且绝不参与 freshness。
        return normalized, "future"
    return normalized, "valid"


def is_sync_state_stale(
    state: DingTalkDirectorySyncState,
    *,
    now: datetime | None = None,
) -> bool:
    reference = timezone.now() if now is None else now
    return reference - sync_state_freshness_at(state) > directory_stale_after()


def build_directory_snapshot(*, now: datetime | None = None) -> dict[str, JsonValue]:
    reference = timezone.now() if now is None else now
    states = {
        (state.source_slug, state.corp_id): state
        for state in DingTalkDirectorySyncState.objects.order_by("source_slug", "corp_id")
    }
    mirror_keys = set(
        cast(
            "list[tuple[str, str]]",
            list(DingTalkUserMirror.objects.values_list("source_slug", "corp_id").distinct()),
        ),
    )
    mirror_keys.update(
        cast(
            "list[tuple[str, str]]",
            list(
                DingTalkDepartmentMirror.objects.values_list(
                    "source_slug",
                    "corp_id",
                ).distinct(),
            ),
        ),
    )
    keys = sorted(set(states) | mirror_keys)
    snapshots: list[JsonValue] = []
    identity_rows: list[list[JsonValue]] = []
    for source_slug, corp_id in keys:
        state = states.get((source_slug, corp_id))
        if state is None:
            status = "missing"
            generation = -1
            snapshot_at: str | None = None
            snapshot_at_status = "missing"
            stale = True
        else:
            status = "error" if state.error else state.status or "unknown"
            generation = state.generation
            snapshot_at, snapshot_at_status = upstream_snapshot_metadata(
                state,
                now=reference,
            )
            stale = status != "success" or is_sync_state_stale(state, now=reference)
        snapshots.append(
            {
                "source_slug": source_slug,
                "corp_id": corp_id,
                "generation": generation,
                "status": status,
                "snapshot_at": snapshot_at,
                "snapshot_at_status": snapshot_at_status,
                "stale": stale,
            },
        )
        identity_rows.append(
            [source_slug, corp_id, generation, status, snapshot_at, snapshot_at_status],
        )

    complete = bool(snapshots) and all(
        isinstance(item, dict)
        and item.get("status") == "success"
        and isinstance(item.get("generation"), int)
        and cast("int", item["generation"]) >= 0
        for item in snapshots
    )
    stale = not snapshots or any(
        isinstance(item, dict) and item.get("stale") is True for item in snapshots
    )
    encoded = dumps(identity_rows, ensure_ascii=False, separators=(",", ":")).encode()
    return {
        "snapshot_id": sha256(encoded).hexdigest(),
        "snapshots": snapshots,
        "stale": stale,
        "complete": complete,
        "authoritative": complete and not stale,
    }
