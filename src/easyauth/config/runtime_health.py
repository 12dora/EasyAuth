from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Final

from django.core.cache import cache

HEARTBEAT_CACHE_PREFIX: Final = "easyauth:runtime-health:"
HEARTBEAT_CACHE_TTL_SECONDS: Final = 86_400
BEAT_WORKER_HEARTBEAT: Final = "beat_worker"
STREAM_PROCESS_HEARTBEAT: Final = "stream_process"
STREAM_ACK_HEARTBEAT: Final = "stream_ack"
GRANT_CLEANUP_SUCCESS: Final = "grant_cleanup_success"
DIRECTORY_SYNC_SUCCESS: Final = "directory_sync_success"
NOTIFY_DELIVERY_SUCCESS: Final = "notify_delivery_success"


@dataclass(frozen=True, slots=True)
class Heartbeat:
    name: str
    recorded_at: float | None
    max_age_seconds: float

    @property
    def age_seconds(self) -> float | None:
        if self.recorded_at is None:
            return None
        return max(0.0, time.time() - self.recorded_at)

    @property
    def healthy(self) -> bool:
        age = self.age_seconds
        return age is not None and age <= self.max_age_seconds


def mark_heartbeat(name: str) -> None:
    cache.set(
        f"{HEARTBEAT_CACHE_PREFIX}{name}",
        time.time(),
        timeout=HEARTBEAT_CACHE_TTL_SECONDS,
    )


def read_heartbeat(name: str, *, max_age_seconds: float) -> Heartbeat:
    value = cache.get(f"{HEARTBEAT_CACHE_PREFIX}{name}")
    recorded_at = float(value) if isinstance(value, int | float) else None
    return Heartbeat(name=name, recorded_at=recorded_at, max_age_seconds=max_age_seconds)
