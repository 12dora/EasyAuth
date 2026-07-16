from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import pytest
from django.test import override_settings

from easyauth.accounts.directory_snapshot import build_directory_snapshot
from easyauth.accounts.models import DingTalkDirectorySyncState

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db


@override_settings(EASYAUTH_DIRECTORY_STALE_AFTER_SECONDS=600)
def test_future_upstream_snapshot_cannot_make_stale_local_sync_authoritative() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    state = DingTalkDirectorySyncState.objects.create(
        source_slug="dingtalk",
        corp_id="corp-clock-skew",
        generation=8,
        status="success",
        finished_at=(now + timedelta(days=1)).isoformat(),
    )
    DingTalkDirectorySyncState.objects.filter(pk=state.pk).update(
        last_synced_at=now - timedelta(seconds=601),
    )

    payload = build_directory_snapshot(now=now)

    snapshot = cast("dict[str, JsonValue]", cast("list[JsonValue]", payload["snapshots"])[0])
    assert snapshot["snapshot_at"] == "2026-07-17T12:00:00+00:00"
    assert snapshot["snapshot_at_status"] == "future"
    assert snapshot["stale"] is True
    assert payload["stale"] is True
    assert payload["complete"] is True
    assert payload["authoritative"] is False


@override_settings(EASYAUTH_DIRECTORY_STALE_AFTER_SECONDS=600)
def test_naive_upstream_snapshot_is_not_exposed_as_valid_timestamp() -> None:
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    state = DingTalkDirectorySyncState.objects.create(
        source_slug="dingtalk",
        corp_id="corp-naive-time",
        generation=9,
        status="success",
        finished_at="2026-07-16T11:59:00",
    )
    DingTalkDirectorySyncState.objects.filter(pk=state.pk).update(
        last_synced_at=now - timedelta(seconds=60),
    )

    payload = build_directory_snapshot(now=now)

    snapshot = cast("dict[str, JsonValue]", cast("list[JsonValue]", payload["snapshots"])[0])
    assert snapshot["snapshot_at"] is None
    assert snapshot["snapshot_at_status"] == "invalid"
    assert snapshot["stale"] is False
    assert payload["authoritative"] is True
