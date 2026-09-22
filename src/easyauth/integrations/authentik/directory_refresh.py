from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace
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

logger = logging.getLogger(__name__)

# Stream 事件驱动的目录刷新: 先让 Authentik 从钉钉拉最新目录, 等它完成后再跑
# EasyAuth 的镜像同步(含离职检出/撤权/交接单)。等待窗口按小目录(数百人)一次
# 全量同步的耗时上限估计; 超时按目录不可用处理, 交给任务重试与定时兜底。
# 超时重试不得盲目再 trigger_sync: 先读 status/, 已成功则只做本地 apply,
# 仍在跑则继续等, 没有覆盖本次触发的同步时才重新触发。
# 重新触发的 user_ids 是标记里已提交的 id 与当前 peek 的并集, 只有这次
# queued=true 之后才从 pending 集合删除。
REFRESH_WAIT_TIMEOUT_SECONDS: Final = 180.0
REFRESH_POLL_INTERVAL_SECONDS: Final = 3.0
REFRESH_TIMEOUT_MESSAGE: Final = "等待 Authentik 钉钉目录同步完成超时。"
REFRESH_UPSTREAM_FAILED_MESSAGE: Final = "Authentik 钉钉目录同步失败。"
REFRESH_TRIGGER_MARKER_TYPE_MESSAGE: Final = "钉钉目录刷新触发标记缓存值类型无效。"
REFRESH_TRIGGER_MARKER_CACHE_KEY_TEMPLATE: Final = (
    "easyauth:dingtalk:stream:refresh-trigger:{corp_id}"
)
# Authentik 增量同步 user_ids 上限(与 REST 契约一致); 超出部分由每日全量同步兜底。
REFRESH_USER_IDS_MAX: Final = 200

# 标记、user_id、trailing、部门标记、触发基线与补刷新去重标志共用下面的 TTL。
# 单次尝试最坏耗时 = 等待超时 + 状态轮询间隔 + status HTTP 超时。
# 截止前的最后一次检查之后仍会 sleep 整段轮询间隔; 紧接着的 get_status
# 最多再占一个 HTTP 超时。该超时与 AuthentikDirectoryClient.timeout_seconds、
# EASYAUTH_AUTHENTIK_OIDC_HTTP_TIMEOUT_SECONDS 的默认值相同, 改默认值必须一起改。
# Celery autoretry 的 retry_backoff=True 因子是 1, countdown = min(backoff_max, 2**retries)。
# request.retries 从 0 起, 真正会睡过去的是 0 .. max_retries-1;
# 第 max_retries 次失败时 retry() 发现下一次将超过上限, 不再等待。
# full_jitter 只把退避缩短到 [0, countdown], 预算按无抖动上界。
# 总预算 = 尝试次数 x 单次最坏 + 退避上界之和 + broker 投递延迟余量。
# 尝试次数 = max_retries + 1。补刷新倒计时 = 总预算。
# TTL = 2 x 总预算, 覆盖「倒计时 + 补刷新自己再打满一次」,
# 稍晚启动的 worker 仍能看见尚未消费的 user_id。
DIRECTORY_REFRESH_MAX_RETRIES: Final = 5
DIRECTORY_REFRESH_RETRY_BACKOFF_MAX_SECONDS: Final = 600
REFRESH_STATUS_HTTP_TIMEOUT_SECONDS: Final = 5
REFRESH_BROKER_DELAY_ALLOWANCE_SECONDS: Final = 300
REFRESH_TTL_STORM_MULTIPLIER: Final = 2
REFRESH_ATTEMPT_COUNT: Final = DIRECTORY_REFRESH_MAX_RETRIES + 1
REFRESH_ATTEMPT_WORST_CASE_SECONDS: Final[int] = (
    int(REFRESH_WAIT_TIMEOUT_SECONDS)
    + int(REFRESH_POLL_INTERVAL_SECONDS)
    + REFRESH_STATUS_HTTP_TIMEOUT_SECONDS
)
REFRESH_RETRY_BACKOFF_BUDGET_SECONDS: Final[int] = sum(
    min(DIRECTORY_REFRESH_RETRY_BACKOFF_MAX_SECONDS, 1 << index)
    for index in range(DIRECTORY_REFRESH_MAX_RETRIES)
)
REFRESH_RETRY_BUDGET_SECONDS: Final[int] = (
    REFRESH_ATTEMPT_COUNT * REFRESH_ATTEMPT_WORST_CASE_SECONDS
    + REFRESH_RETRY_BACKOFF_BUDGET_SECONDS
    + REFRESH_BROKER_DELAY_ALLOWANCE_SECONDS
)
REFRESH_MARKER_TTL_SECONDS: Final[int] = (
    REFRESH_RETRY_BUDGET_SECONDS * REFRESH_TTL_STORM_MULTIPLIER
)

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
class DirectoryRefreshHooks:
    """目录刷新挂点。peek 在决定重新触发时读取当前 pending, 不是任务开始时的快照。"""

    on_accepted_user_ids: Callable[[tuple[str, ...]], None] | None = None
    before_trigger: Callable[[], None] | None = None
    before_apply: Callable[[], None] | None = None
    peek_user_ids: Callable[[], Sequence[str]] | None = None


_NO_REFRESH_HOOKS: Final = DirectoryRefreshHooks()


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
    hooks: DirectoryRefreshHooks


def refresh_trigger_marker_cache_key(corp_id: str) -> str:
    return REFRESH_TRIGGER_MARKER_CACHE_KEY_TEMPLATE.format(corp_id=corp_id)


def refresh_trigger_marker_ttl(corp_id: str) -> None:
    # 延迟补刷新启动时仍要能读到这次触发基线; 没有标记则不做任何事。
    marker = _load_trigger_marker(corp_id)
    if marker is None:
        return
    _store_trigger_marker(corp_id, baseline=marker.baseline, user_ids=marker.user_ids)


def refresh_dingtalk_directory(
    client: AuthentikDirectoryRefreshClient,
    corp_id: str,
    *,
    user_ids: Sequence[str] = (),
    wait_policy: RefreshWaitPolicy = DEFAULT_REFRESH_WAIT_POLICY,
    hooks: DirectoryRefreshHooks | None = None,
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
        hooks=hooks or _NO_REFRESH_HOOKS,
    )
    marker = _load_trigger_marker(corp_id)
    if marker is not None:
        return _resume_triggered_refresh(call, marker)
    return _trigger_and_wait(call)


def _trigger_and_wait(call: _RefreshCall) -> AuthentikDirectorySyncResult | None:
    _run_before_trigger(call)
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
    # 等待超时后的 Celery 重试: 按 status 决定本地 apply / 继续等 / 重新触发。
    # 重新触发前不删除 pending id, 避免这次请求丢掉上一轮已经提交的离职人员。
    entry = _corp_sync_entry(call.client, call.corp_id)
    covering = _covering_state(entry, baseline=marker.baseline)
    if covering == _COVERING_SUCCESS:
        _notify_accepted(call, marker.user_ids)
        return _apply_and_clear_marker(call)
    if covering == _COVERING_ERROR:
        _notify_accepted(call, marker.user_ids)
        _clear_trigger_marker(call.corp_id)
        raise AuthentikDirectoryUnavailableError(_upstream_error_message(call.corp_id, entry))
    if covering == _COVERING_IN_FLIGHT:
        _notify_accepted(call, marker.user_ids)
        return _wait_and_apply(call, baseline=marker.baseline)
    return _retrigger_after_absent(call, marker)


def _retrigger_after_absent(
    call: _RefreshCall,
    marker: _TriggerMarker,
) -> AuthentikDirectorySyncResult | None:
    merged = _retrigger_user_ids(call, marker)
    # queued=false 时保留标记, 下次重试仍带得上 marker 里的 id。
    _store_trigger_marker(call.corp_id, baseline=marker.baseline, user_ids=merged)
    return _trigger_and_wait(replace(call, user_ids=merged))


def _retrigger_user_ids(call: _RefreshCall, marker: _TriggerMarker) -> tuple[str, ...]:
    if call.hooks.peek_user_ids is None:
        current = call.user_ids
    else:
        current = tuple(call.hooks.peek_user_ids())
    return _bounded_trigger_ids(call.corp_id, [*marker.user_ids, *current])


def _bounded_trigger_ids(corp_id: str, user_ids: list[str]) -> tuple[str, ...]:
    merged = list(dict.fromkeys(user_id for user_id in user_ids if user_id))
    overflow = len(merged) - REFRESH_USER_IDS_MAX
    if overflow <= 0:
        return tuple(merged)
    logger.warning(
        "钉钉目录重触发 user_ids 超过 %s, 只保留先到 %s 个, 余下由每日全量兜底; corp=%s dropped=%s",
        REFRESH_USER_IDS_MAX,
        REFRESH_USER_IDS_MAX,
        corp_id,
        overflow,
    )
    return tuple(merged[:REFRESH_USER_IDS_MAX])


def _wait_and_apply(call: _RefreshCall, *, baseline: str) -> AuthentikDirectorySyncResult:
    _wait_for_sync_completion(
        call.client,
        call.corp_id,
        baseline=baseline,
        policy=call.wait_policy,
    )
    return _apply_and_clear_marker(call)


def _apply_and_clear_marker(call: _RefreshCall) -> AuthentikDirectorySyncResult:
    _run_before_apply(call)
    # Authentik 每次成功同步都会推进快照代际, 触发完成后本地写入路径会执行,
    # 不必再把这次等待的 finished_at 当作跳过条件。
    result = sync_authentik_dingtalk_directory(call.client)
    _clear_trigger_marker(call.corp_id)
    return result


def _run_before_trigger(call: _RefreshCall) -> None:
    if call.hooks.before_trigger is not None:
        call.hooks.before_trigger()


def _run_before_apply(call: _RefreshCall) -> None:
    if call.hooks.before_apply is not None:
        call.hooks.before_apply()


def _notify_accepted(call: _RefreshCall, user_ids: tuple[str, ...]) -> None:
    if call.hooks.on_accepted_user_ids is not None:
        call.hooks.on_accepted_user_ids(user_ids)


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
        timeout=REFRESH_MARKER_TTL_SECONDS,
    )


def _clear_trigger_marker(corp_id: str) -> None:
    _ = cache.delete(refresh_trigger_marker_cache_key(corp_id))


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""
