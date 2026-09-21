from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Protocol, cast

from django.core.cache import cache

from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryUnavailableError,
)
from easyauth.integrations.authentik.directory_sync import sync_authentik_dingtalk_directory

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from easyauth.integrations.authentik.directory_client import DirectorySyncTriggerResult
    from easyauth.integrations.authentik.directory_payloads import DirectoryJson
    from easyauth.integrations.authentik.directory_sync import AuthentikDirectorySyncResult

# Stream 事件驱动的目录刷新: 先让 Authentik 从钉钉拉最新目录, 等它完成后再跑
# EasyAuth 的镜像同步(含离职检出/撤权/交接单)。等待窗口按小目录(数百人)一次
# 全量同步的耗时上限估计; 超时按目录不可用处理, 交给任务重试与定时兜底。
# 超时重试不得盲目再 trigger_sync: 先读 status/, 已成功则只做本地 apply,
# 仍在跑则继续等, 没有覆盖本次触发的同步时才重新触发。
REFRESH_WAIT_TIMEOUT_SECONDS: Final = 180.0
REFRESH_POLL_INTERVAL_SECONDS: Final = 3.0
REFRESH_TIMEOUT_MESSAGE: Final = "等待 Authentik 钉钉目录同步完成超时。"
REFRESH_UPSTREAM_FAILED_MESSAGE: Final = "Authentik 钉钉目录同步失败。"
REFRESH_TRIGGER_MARKER_TYPE_MESSAGE: Final = "钉钉目录刷新触发标记缓存值类型无效。"
REFRESH_TRIGGER_MARKER_CACHE_KEY_TEMPLATE: Final = (
    "easyauth:dingtalk:stream:refresh-trigger:{corp_id}"
)
# 覆盖 180s 等待 + Celery 重试退避窗口, 避免重试时丢失本次触发基线。
REFRESH_TRIGGER_MARKER_TTL_SECONDS: Final = int(REFRESH_WAIT_TIMEOUT_SECONDS) + 600

AUTHENTIK_SYNC_STATUS_SUCCESS: Final = "success"
AUTHENTIK_SYNC_STATUS_ERROR: Final = "error"

_COVERING_SUCCESS: Final = "success"
_COVERING_ERROR: Final = "error"
_COVERING_IN_FLIGHT: Final = "in_flight"
_COVERING_ABSENT: Final = "absent"


@dataclass(frozen=True, slots=True)
class RefreshWaitPolicy:
    """等待 Authentik 同步完成的节奏参数; sleep/monotonic 可注入以便测试。"""

    timeout_seconds: float = REFRESH_WAIT_TIMEOUT_SECONDS
    poll_interval_seconds: float = REFRESH_POLL_INTERVAL_SECONDS
    sleep: Callable[[float], None] = field(default=time.sleep)
    monotonic: Callable[[], float] = field(default=time.monotonic)


DEFAULT_REFRESH_WAIT_POLICY: Final = RefreshWaitPolicy()


class AuthentikDirectoryRefreshClient(Protocol):
    def get_status(self) -> object: ...

    def trigger_sync(
        self,
        corp_id: str,
        *,
        user_ids: Sequence[str] = (),
    ) -> DirectorySyncTriggerResult: ...

    def iter_departments(self) -> Iterable[object]: ...

    def iter_users(self) -> Iterable[object]: ...

    def get_user_org(self, corp_id: str, user_id: str) -> object: ...


@dataclass(frozen=True, slots=True)
class _TriggerMarker:
    baseline: str
    user_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RefreshCall:
    client: AuthentikDirectoryRefreshClient
    corp_id: str
    user_ids: tuple[str, ...]
    wait_policy: RefreshWaitPolicy
    on_accepted_user_ids: Callable[[tuple[str, ...]], None] | None


def refresh_trigger_marker_cache_key(corp_id: str) -> str:
    return REFRESH_TRIGGER_MARKER_CACHE_KEY_TEMPLATE.format(corp_id=corp_id)


def refresh_dingtalk_directory(
    client: AuthentikDirectoryRefreshClient,
    corp_id: str,
    *,
    user_ids: Sequence[str] = (),
    wait_policy: RefreshWaitPolicy = DEFAULT_REFRESH_WAIT_POLICY,
    on_accepted_user_ids: Callable[[tuple[str, ...]], None] | None = None,
) -> AuthentikDirectorySyncResult | None:
    # 以 Authentik 自己记录的 finished_at 为基线判断"这次触发的同步已完成",
    # 避免 EasyAuth 与 Authentik 主机时钟偏差造成误判。
    # queued=false: 进行中的同步可能早于本批事件启动, user_ids 未被记录;
    # 不 round-trip 等待, 由调用方把 user_ids 留在 pending 并在冷却后 trailing。
    call = _RefreshCall(
        client=client,
        corp_id=corp_id,
        user_ids=tuple(user_ids),
        wait_policy=wait_policy,
        on_accepted_user_ids=on_accepted_user_ids,
    )
    marker = _load_trigger_marker(corp_id)
    if marker is not None:
        return _resume_triggered_refresh(call, marker)
    return _trigger_and_wait(call)


def _trigger_and_wait(call: _RefreshCall) -> AuthentikDirectorySyncResult | None:
    baseline = _corp_finished_at(call.client, call.corp_id)
    trigger = call.client.trigger_sync(call.corp_id, user_ids=call.user_ids)
    if not trigger.queued:
        return None
    _store_trigger_marker(call.corp_id, baseline=baseline, user_ids=call.user_ids)
    _notify_accepted(call, call.user_ids)
    return _wait_and_apply(call, baseline=baseline)


def _resume_triggered_refresh(
    call: _RefreshCall,
    marker: _TriggerMarker,
) -> AuthentikDirectorySyncResult | None:
    # 等待超时后的 Celery 重试: 先承认上次已 queued 的 ids, 再按 status 决定
    # 本地 apply / 继续等 / 重新触发, 禁止盲目第二次 trigger_sync。
    _notify_accepted(call, marker.user_ids)
    entry = _corp_sync_entry(call.client, call.corp_id)
    covering = _covering_state(entry, baseline=marker.baseline)
    if covering == _COVERING_SUCCESS:
        return _apply_and_clear_marker(call)
    if covering == _COVERING_ERROR:
        _clear_trigger_marker(call.corp_id)
        raise AuthentikDirectoryUnavailableError(_upstream_error_message(call.corp_id, entry))
    if covering == _COVERING_IN_FLIGHT:
        return _wait_and_apply(call, baseline=marker.baseline)
    _clear_trigger_marker(call.corp_id)
    return _trigger_and_wait(call)


def _wait_and_apply(call: _RefreshCall, *, baseline: str) -> AuthentikDirectorySyncResult:
    _wait_for_sync_completion(
        call.client,
        call.corp_id,
        baseline=baseline,
        policy=call.wait_policy,
    )
    return _apply_and_clear_marker(call)


def _apply_and_clear_marker(call: _RefreshCall) -> AuthentikDirectorySyncResult:
    result = sync_authentik_dingtalk_directory(call.client)
    _clear_trigger_marker(call.corp_id)
    return result


def _notify_accepted(call: _RefreshCall, user_ids: tuple[str, ...]) -> None:
    if call.on_accepted_user_ids is not None:
        call.on_accepted_user_ids(user_ids)


def _covering_state(entry: DirectoryJson | None, *, baseline: str) -> str:
    if entry is None:
        return _COVERING_ABSENT
    finished_at = _string(entry.get("finished_at"))
    status = _string(entry.get("status"))
    if finished_at and finished_at != baseline:
        if status == AUTHENTIK_SYNC_STATUS_SUCCESS:
            return _COVERING_SUCCESS
        if status == AUTHENTIK_SYNC_STATUS_ERROR:
            return _COVERING_ERROR
        return _COVERING_IN_FLIGHT
    if status in {AUTHENTIK_SYNC_STATUS_SUCCESS, AUTHENTIK_SYNC_STATUS_ERROR}:
        return _COVERING_ABSENT
    return _COVERING_IN_FLIGHT


def _wait_for_sync_completion(
    client: AuthentikDirectoryRefreshClient,
    corp_id: str,
    *,
    baseline: str,
    policy: RefreshWaitPolicy,
) -> None:
    deadline = policy.monotonic() + policy.timeout_seconds
    while True:
        entry = _corp_sync_entry(client, corp_id)
        if entry is not None:
            finished_at = _string(entry.get("finished_at"))
            status = _string(entry.get("status"))
            if finished_at and finished_at != baseline:
                if status == AUTHENTIK_SYNC_STATUS_SUCCESS:
                    return
                if status == AUTHENTIK_SYNC_STATUS_ERROR:
                    raise AuthentikDirectoryUnavailableError(
                        _upstream_error_message(corp_id, entry),
                    )
                # 其余状态(如 running 的中间落库)继续等待, 直到出现终态。
        if policy.monotonic() >= deadline:
            message = f"{REFRESH_TIMEOUT_MESSAGE}: corp={corp_id}"
            raise AuthentikDirectoryUnavailableError(message)
        policy.sleep(policy.poll_interval_seconds)


def _upstream_error_message(corp_id: str, entry: DirectoryJson | None) -> str:
    error = _string(entry.get("error")) if entry is not None else ""
    return f"{REFRESH_UPSTREAM_FAILED_MESSAGE}: corp={corp_id} {error}".rstrip()


def _corp_finished_at(client: AuthentikDirectoryRefreshClient, corp_id: str) -> str:
    entry = _corp_sync_entry(client, corp_id)
    return _string(entry.get("finished_at")) if entry is not None else ""


def _corp_sync_entry(
    client: AuthentikDirectoryRefreshClient,
    corp_id: str,
) -> DirectoryJson | None:
    status = client.get_status()
    sync_items = getattr(status, "sync", ())
    if not isinstance(sync_items, tuple):
        return None
    for item in cast("tuple[object, ...]", sync_items):
        if not isinstance(item, dict):
            continue
        entry = cast("DirectoryJson", item)
        if _string(entry.get("corp_id")) == corp_id:
            return entry
    return None


def _load_trigger_marker(corp_id: str) -> _TriggerMarker | None:
    raw = cast("object", cache.get(refresh_trigger_marker_cache_key(corp_id)))
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError(REFRESH_TRIGGER_MARKER_TYPE_MESSAGE)
    payload = cast("dict[str, object]", raw)
    baseline = payload.get("baseline")
    user_ids = payload.get("user_ids")
    if not isinstance(baseline, str) or not isinstance(user_ids, list | tuple):
        raise TypeError(REFRESH_TRIGGER_MARKER_TYPE_MESSAGE)
    return _TriggerMarker(
        baseline=baseline,
        user_ids=_marker_user_ids(cast("list[object] | tuple[object, ...]", user_ids)),
    )


def _marker_user_ids(user_ids: list[object] | tuple[object, ...]) -> tuple[str, ...]:
    items: list[str] = []
    for item in user_ids:
        if not isinstance(item, str):
            raise TypeError(REFRESH_TRIGGER_MARKER_TYPE_MESSAGE)
        items.append(item)
    return tuple(items)


def _store_trigger_marker(
    corp_id: str,
    *,
    baseline: str,
    user_ids: Sequence[str],
) -> None:
    cache.set(
        refresh_trigger_marker_cache_key(corp_id),
        {"baseline": baseline, "user_ids": list(user_ids)},
        timeout=REFRESH_TRIGGER_MARKER_TTL_SECONDS,
    )


def _clear_trigger_marker(corp_id: str) -> None:
    _ = cache.delete(refresh_trigger_marker_cache_key(corp_id))


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""
