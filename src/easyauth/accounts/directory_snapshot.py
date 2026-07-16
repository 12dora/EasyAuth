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


def sync_state_snapshot_at(state: DingTalkDirectorySyncState) -> datetime:
    if state.finished_at:
        try:
            parsed = datetime.fromisoformat(state.finished_at)
        except ValueError:
            pass
        else:
            if parsed.tzinfo is not None:
                return parsed
    return state.last_synced_at


def is_sync_state_stale(
    state: DingTalkDirectorySyncState,
    *,
    now: datetime | None = None,
) -> bool:
    reference = timezone.now() if now is None else now
    return reference - sync_state_snapshot_at(state) > directory_stale_after()


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
            stale = True
        else:
            status = "error" if state.error else state.status or "unknown"
            generation = state.generation
            snapshot_at = sync_state_snapshot_at(state).isoformat()
            stale = status != "success" or is_sync_state_stale(state, now=reference)
        snapshots.append(
            {
                "source_slug": source_slug,
                "corp_id": corp_id,
                "generation": generation,
                "status": status,
                "snapshot_at": snapshot_at,
                "stale": stale,
            },
        )
        identity_rows.append([source_slug, corp_id, generation, status, snapshot_at])

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
