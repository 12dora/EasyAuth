from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from easyauth.config.runtime_health import STREAM_PROCESS_HEARTBEAT
from easyauth.integrations.management.commands import run_dingtalk_stream

if TYPE_CHECKING:
    import pytest


class CacheUnavailableError(RuntimeError):
    pass


def test_stream_heartbeat_continues_after_cache_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = threading.Event()
    calls: list[str] = []

    def flaky_mark_heartbeat(name: str) -> None:
        calls.append(name)
        if len(calls) == 1:
            raise CacheUnavailableError
        stop.set()

    monkeypatch.setattr(run_dingtalk_stream, "mark_heartbeat", flaky_mark_heartbeat)
    monkeypatch.setattr(run_dingtalk_stream, "STREAM_HEARTBEAT_INTERVAL_SECONDS", 0.001)

    run_dingtalk_stream.heartbeat_loop(stop)

    assert calls == [
        STREAM_PROCESS_HEARTBEAT,
        STREAM_PROCESS_HEARTBEAT,
    ]
