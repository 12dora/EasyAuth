from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Final, cast

from django.core.cache import cache

from easyauth.integrations.authentik.directory_refresh import (
    REFRESH_MARKER_TTL_SECONDS,
    REFRESH_USER_IDS_MAX,
    REFRESH_WAIT_TIMEOUT_SECONDS,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

logger = logging.getLogger(__name__)

# 合并窗口的 pending 标记只负责挡住重复入队, TTL 短于重试预算:
# 任务丢失后不能把整个 corp 锁死一整段重试。user_ids / trailing / 部门标记 /
# 触发基线用 REFRESH_MARKER_TTL_SECONDS, 覆盖整段 Celery 重试预算。
REFRESH_PENDING_CACHE_KEY_TEMPLATE: Final = "easyauth:dingtalk:stream:refresh-pending:{corp_id}"
REFRESH_USER_IDS_CACHE_KEY_TEMPLATE: Final = "easyauth:dingtalk:stream:refresh-user-ids:{corp_id}"
REFRESH_USER_IDS_LOCK_CACHE_KEY_TEMPLATE: Final = (
    "easyauth:dingtalk:stream:refresh-user-ids-lock:{corp_id}"
)
REFRESH_LAST_TRIGGERED_CACHE_KEY_TEMPLATE: Final = (
    "easyauth:dingtalk:stream:refresh-last-triggered:{corp_id}"
)
REFRESH_REQUEUE_CACHE_KEY_TEMPLATE: Final = "easyauth:dingtalk:stream:refresh-requeue:{corp_id}"
REFRESH_RUNNING_CACHE_KEY_TEMPLATE: Final = "easyauth:dingtalk:stream:refresh-running:{corp_id}"
REFRESH_TRAILING_CACHE_KEY_TEMPLATE: Final = "easyauth:dingtalk:stream:refresh-trailing:{corp_id}"
REFRESH_DEPT_EVENT_CACHE_KEY_TEMPLATE: Final = (
    "easyauth:dingtalk:stream:refresh-dept-event:{corp_id}"
)
REFRESH_FOLLOWUP_CACHE_KEY_TEMPLATE: Final = "easyauth:dingtalk:stream:refresh-followup:{corp_id}"
REFRESH_COALESCE_SECONDS: Final = 30
REFRESH_PENDING_TTL_SECONDS: Final = 600
REFRESH_MIN_INTERVAL_SECONDS: Final = 120
# 本地 apply 按数百次组织 HTTP(单次超时 5 秒)留出的预算, 加上等待构成锁 TTL。
REFRESH_APPLY_BUDGET_SECONDS: Final = 600
REFRESH_RUNNING_LOCK_TTL_SECONDS: Final = (
    int(REFRESH_WAIT_TIMEOUT_SECONDS) + REFRESH_APPLY_BUDGET_SECONDS
)
# 硬超时低于锁 TTL, 软超时再低一档, 使任务被杀掉时锁仍在, finally 也来得及释放。
REFRESH_TASK_TIME_LIMIT_SLACK_SECONDS: Final = 30
REFRESH_TASK_TIME_LIMIT_SECONDS: Final = (
    REFRESH_RUNNING_LOCK_TTL_SECONDS - REFRESH_TASK_TIME_LIMIT_SLACK_SECONDS
)
REFRESH_TASK_SOFT_TIME_LIMIT_SECONDS: Final = (
    REFRESH_TASK_TIME_LIMIT_SECONDS - REFRESH_TASK_TIME_LIMIT_SLACK_SECONDS
)
# queued=false 时最多连续再调度次数, 避免在 Authentik 长事务上忙等烧配额。
REFRESH_MAX_CONSECUTIVE_REQUEUES: Final = 3
REFRESH_USER_IDS_LOCK_TTL_SECONDS: Final = 5
REFRESH_USER_IDS_LOCK_ATTEMPTS: Final = 20
REFRESH_USER_IDS_LOCK_SLEEP_SECONDS: Final = 0.05
# 去重标志要活过「倒计时 + 补刷新自己再耗尽一次预算」, 避免失败后又排下一次。
_FOLLOWUP_FLAG_BUDGET_MULTIPLIER: Final = 2
REFRESH_FOLLOWUP_FLAG_TTL_SECONDS: Final = (
    REFRESH_MARKER_TTL_SECONDS * _FOLLOWUP_FLAG_BUDGET_MULTIPLIER
)
REFRESH_USER_IDS_LOCK_FAILED_MESSAGE: Final = "钉钉目录刷新 user_ids 缓存锁获取失败。"
REFRESH_CACHE_TYPE_MESSAGE: Final = "钉钉目录刷新缓存值类型无效。"
REFRESH_RUNNING_LOCK_LOST_MESSAGE: Final = "钉钉目录刷新 running 锁已不属于当前任务。"

_TRAILING_FLAG: Final = "1"
_PENDING_FLAG: Final = "1"


def accumulate_refresh_user_ids(corp_id: str, user_ids: Sequence[str]) -> None:
    incoming = [item for item in user_ids if item]
    if not incoming:
        return

    def _merge(current: list[str]) -> list[str]:
        return _bounded_user_ids(corp_id, [*current, *incoming])

    _ = _with_user_ids_lock(corp_id, _merge)
    _refresh_trailing_ttl(corp_id)


def peek_pending_user_ids(corp_id: str) -> tuple[str, ...]:
    peeked: list[str] = []

    def _copy(current: list[str]) -> list[str]:
        peeked.extend(current)
        return current

    _ = _with_user_ids_lock(corp_id, _copy)
    return tuple(peeked)


def remove_sent_user_ids(corp_id: str, user_ids: Sequence[str]) -> None:
    sent = {item for item in user_ids if item}
    if not sent:
        return

    def _drop(current: list[str]) -> list[str]:
        return [item for item in current if item not in sent]

    _ = _with_user_ids_lock(corp_id, _drop)


def running_lock_held(corp_id: str) -> bool:
    raw = _cache_value(REFRESH_RUNNING_CACHE_KEY_TEMPLATE, corp_id)
    if raw is None:
        return False
    if not isinstance(raw, str) or not raw:
        raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
    return True


def acquire_running_lock(corp_id: str) -> str | None:
    token = uuid.uuid4().hex
    added = cache.add(
        _corp_key(REFRESH_RUNNING_CACHE_KEY_TEMPLATE, corp_id),
        token,
        timeout=REFRESH_RUNNING_LOCK_TTL_SECONDS,
    )
    if added:
        return token
    return None


def extend_running_lock(corp_id: str, token: str) -> None:
    key = _corp_key(REFRESH_RUNNING_CACHE_KEY_TEMPLATE, corp_id)
    current = cast("object", cache.get(key))
    if current != token:
        raise RuntimeError(REFRESH_RUNNING_LOCK_LOST_MESSAGE)
    # get 与 set 之间锁可能过期并被其他 worker 占用, 本次 set 会覆盖对方 token。
    # 锁 TTL 长于任务 time_limit, 任务仍在执行时不会自然到期。
    cache.set(key, token, timeout=REFRESH_RUNNING_LOCK_TTL_SECONDS)


def release_running_lock(corp_id: str, token: str) -> None:
    key = _corp_key(REFRESH_RUNNING_CACHE_KEY_TEMPLATE, corp_id)
    # get 与 delete 不是原子操作。读到新 token 时不会删除; 读到旧 token 后、
    # delete 前被换锁的窗口无法用普通 cache.delete 消除。任务 time_limit 低于
    # 锁 TTL, 正常运行期间锁不会先过期。
    current = cast("object", cache.get(key))
    if current == token:
        _ = cache.delete(key)


def set_pending_marker(corp_id: str) -> None:
    _ = cache.add(
        _corp_key(REFRESH_PENDING_CACHE_KEY_TEMPLATE, corp_id),
        _PENDING_FLAG,
        timeout=REFRESH_PENDING_TTL_SECONDS,
    )


def pending_marker_exists(corp_id: str) -> bool:
    raw = _cache_value(REFRESH_PENDING_CACHE_KEY_TEMPLATE, corp_id)
    if raw is None:
        return False
    if raw != _PENDING_FLAG:
        raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
    return True


def delete_pending_marker(corp_id: str) -> None:
    _ = cache.delete(_corp_key(REFRESH_PENDING_CACHE_KEY_TEMPLATE, corp_id))


def mark_trailing_needed(corp_id: str) -> None:
    cache.set(
        _corp_key(REFRESH_TRAILING_CACHE_KEY_TEMPLATE, corp_id),
        _TRAILING_FLAG,
        timeout=REFRESH_MARKER_TTL_SECONDS,
    )


def consume_trailing_needed(corp_id: str) -> bool:
    key = _corp_key(REFRESH_TRAILING_CACHE_KEY_TEMPLATE, corp_id)
    raw = cast("object", cache.get(key))
    _ = cache.delete(key)
    if raw is None:
        return False
    if raw != _TRAILING_FLAG:
        raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
    return True


def increment_requeue_count(corp_id: str) -> int:
    # 计数 TTL 短于延迟补刷新倒计时, 补刷新开始时计数已过期, 重新获得 queued=false 预算。
    key = _corp_key(REFRESH_REQUEUE_CACHE_KEY_TEMPLATE, corp_id)
    if cache.add(key, 1, timeout=REFRESH_PENDING_TTL_SECONDS):
        return 1
    try:
        count = cast("object", cache.incr(key))
    except ValueError:
        cache.set(key, 1, timeout=REFRESH_PENDING_TTL_SECONDS)
        return 1
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
    return count


def delete_requeue_count(corp_id: str) -> None:
    _ = cache.delete(_corp_key(REFRESH_REQUEUE_CACHE_KEY_TEMPLATE, corp_id))


def mark_sync_triggered(corp_id: str) -> None:
    cache.set(
        _corp_key(REFRESH_LAST_TRIGGERED_CACHE_KEY_TEMPLATE, corp_id),
        time.time(),
        timeout=REFRESH_MIN_INTERVAL_SECONDS,
    )


def refresh_countdown(corp_id: str) -> float:
    remaining = _timestamp_remaining_seconds(
        _cache_value(REFRESH_LAST_TRIGGERED_CACHE_KEY_TEMPLATE, corp_id),
        extra_seconds=float(REFRESH_MIN_INTERVAL_SECONDS),
    )
    if remaining > 0:
        return remaining
    return float(REFRESH_COALESCE_SECONDS)


def mark_dept_event_pending(corp_id: str) -> None:
    cache.set(
        _corp_key(REFRESH_DEPT_EVENT_CACHE_KEY_TEMPLATE, corp_id),
        uuid.uuid4().hex,
        timeout=REFRESH_MARKER_TTL_SECONDS,
    )


def read_dept_event_token(corp_id: str) -> str | None:
    raw = _cache_value(REFRESH_DEPT_EVENT_CACHE_KEY_TEMPLATE, corp_id)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw:
        raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
    return raw


def clear_dept_event_token(corp_id: str, token: str) -> None:
    key = _corp_key(REFRESH_DEPT_EVENT_CACHE_KEY_TEMPLATE, corp_id)
    # 与 running 锁相同的 get/delete 竞态。每次部门事件换新 token,
    # 触发期间新到的部门事件不会被这次 queued=true 清掉。
    current = cast("object", cache.get(key))
    if current == token:
        _ = cache.delete(key)


def trailing_refresh_should_trigger(corp_id: str) -> bool:
    if peek_pending_user_ids(corp_id):
        return True
    return read_dept_event_token(corp_id) is not None


def claim_exhaustion_followup(corp_id: str) -> bool:
    if not _has_exhaustion_followup_work(corp_id):
        return False
    _refresh_trailing_ttl(corp_id)
    _refresh_dept_token_ttl(corp_id)
    key = _corp_key(REFRESH_FOLLOWUP_CACHE_KEY_TEMPLATE, corp_id)
    if cache.add(key, _PENDING_FLAG, timeout=REFRESH_FOLLOWUP_FLAG_TTL_SECONDS):
        return True
    raw = cast("object", cache.get(key))
    if raw != _PENDING_FLAG:
        raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
    return False


def clear_exhaustion_followup(corp_id: str) -> None:
    _ = cache.delete(_corp_key(REFRESH_FOLLOWUP_CACHE_KEY_TEMPLATE, corp_id))


def _has_exhaustion_followup_work(corp_id: str) -> bool:
    # peek 会把仍在的 user_ids 写回并续期, 延迟补刷新启动时 id 还在。
    if peek_pending_user_ids(corp_id):
        return True
    if _trailing_flag_exists(corp_id):
        return True
    return read_dept_event_token(corp_id) is not None


def _trailing_flag_exists(corp_id: str) -> bool:
    raw = _cache_value(REFRESH_TRAILING_CACHE_KEY_TEMPLATE, corp_id)
    if raw is None:
        return False
    if raw != _TRAILING_FLAG:
        raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
    return True


def _refresh_trailing_ttl(corp_id: str) -> None:
    raw = _cache_value(REFRESH_TRAILING_CACHE_KEY_TEMPLATE, corp_id)
    if raw is None:
        return
    if raw != _TRAILING_FLAG:
        raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
    cache.set(
        _corp_key(REFRESH_TRAILING_CACHE_KEY_TEMPLATE, corp_id),
        _TRAILING_FLAG,
        timeout=REFRESH_MARKER_TTL_SECONDS,
    )


def _refresh_dept_token_ttl(corp_id: str) -> None:
    token = read_dept_event_token(corp_id)
    if token is None:
        return
    cache.set(
        _corp_key(REFRESH_DEPT_EVENT_CACHE_KEY_TEMPLATE, corp_id),
        token,
        timeout=REFRESH_MARKER_TTL_SECONDS,
    )


def _bounded_user_ids(corp_id: str, user_ids: list[str]) -> list[str]:
    merged = list(dict.fromkeys(user_ids))
    overflow = len(merged) - REFRESH_USER_IDS_MAX
    if overflow <= 0:
        return merged
    logger.warning(
        "钉钉目录刷新 user_ids 超过 %s, 只保留先到的 %s 个, 其余由每日全量兜底; corp=%s dropped=%s",
        REFRESH_USER_IDS_MAX,
        REFRESH_USER_IDS_MAX,
        corp_id,
        overflow,
    )
    return merged[:REFRESH_USER_IDS_MAX]


def _with_user_ids_lock(
    corp_id: str,
    mutator: Callable[[list[str]], list[str]],
) -> list[str]:
    lock_key = _corp_key(REFRESH_USER_IDS_LOCK_CACHE_KEY_TEMPLATE, corp_id)
    ids_key = _corp_key(REFRESH_USER_IDS_CACHE_KEY_TEMPLATE, corp_id)
    for _attempt in range(REFRESH_USER_IDS_LOCK_ATTEMPTS):
        if cache.add(lock_key, _PENDING_FLAG, timeout=REFRESH_USER_IDS_LOCK_TTL_SECONDS):
            try:
                updated = mutator(_read_cached_user_ids(ids_key))
                _write_cached_user_ids(ids_key, updated)
                return updated
            finally:
                _ = cache.delete(lock_key)
        time.sleep(REFRESH_USER_IDS_LOCK_SLEEP_SECONDS)
    raise RuntimeError(REFRESH_USER_IDS_LOCK_FAILED_MESSAGE)


def _read_cached_user_ids(ids_key: str) -> list[str]:
    raw = cast("object", cache.get(ids_key))
    if raw is None:
        return []
    if not isinstance(raw, list | tuple):
        raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
    items: list[str] = []
    for item in cast("list[object] | tuple[object, ...]", raw):
        if not isinstance(item, str):
            raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
        if item:
            items.append(item)
    return items


def _write_cached_user_ids(ids_key: str, user_ids: list[str]) -> None:
    # 每次写回都续期。peek 与累积都会走到这里, 重试期间 id 不会中途过期。
    if not user_ids:
        _ = cache.delete(ids_key)
        return
    cache.set(ids_key, user_ids, timeout=REFRESH_MARKER_TTL_SECONDS)


def _timestamp_remaining_seconds(raw: object, *, extra_seconds: float = 0.0) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
    remaining = float(raw) + extra_seconds - time.time()
    return remaining if remaining > 0 else 0.0


def _cache_value(template: str, corp_id: str) -> object:
    return cast("object", cache.get(_corp_key(template, corp_id)))


def _corp_key(template: str, corp_id: str) -> str:
    return template.format(corp_id=corp_id)
