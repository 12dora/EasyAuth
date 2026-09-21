from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import TYPE_CHECKING, Final, Literal, cast

from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import F, Value
from django.db.models.functions import Greatest
from django.utils import timezone
from redis.exceptions import RedisError

from easyauth.integrations.dingtalk.errors import DingTalkCallBudgetExceededError
from easyauth.usage.models import UsageBucket
from easyauth.usage.registry import CATEGORIES, SOURCE_EASYAUTH, category

if TYPE_CHECKING:
    from datetime import date, datetime

    from easyauth.usage.registry import UsageCategory

logger = logging.getLogger(__name__)

COUNTER_TTL_DAYS: Final = 3
COUNTER_TTL_SECONDS: Final = COUNTER_TTL_DAYS * 24 * 60 * 60
OPEN_HOUR_WINDOW: Final = 3
CACHE_WARNING_INTERVAL_SECONDS: Final = 60.0
_COUNTER_KIND_COUNT: Final = "c"
_COUNTER_KIND_BLOCKED: Final = "b"
type _CounterKind = Literal["c", "b"]


class _CacheMeteringError(Exception):
    pass


_CACHE_BACKEND_ERRORS: Final = (
    OSError,
    ConnectionError,
    TimeoutError,
    NotImplementedError,
    RedisError,
    _CacheMeteringError,
)


@dataclass
class _WarnGate:
    last_at: float = 0.0


_CACHE_WARN_GATE = _WarnGate()


def record_and_check(category_key: str) -> None:
    spec = category(category_key)
    if not _decide(spec):
        _refuse(spec)
    _increment_allowed(spec)


def record(category_key: str, *, count: int = 1) -> None:
    spec = category(category_key)
    if count < 1:
        message = "用量计数增量必须是正整数。"
        raise ValueError(message)
    hour_start = truncate_hour_utc(timezone.now())
    _ = _try_incr(_counter_key(hour_start, spec.key, _COUNTER_KIND_COUNT), count)


def current_hour_counts() -> dict[str, tuple[int, int]]:
    return cached_hour_counts(truncate_hour_utc(timezone.now()))


def cached_hour_counts(hour_start: datetime) -> dict[str, tuple[int, int]]:
    try:
        return _read_hour_counts(hour_start)
    except _CACHE_BACKEND_ERRORS as error:
        _warn_cache_failure(error)
        return {}


def open_hour_starts(*, now: datetime | None = None) -> tuple[datetime, ...]:
    current = truncate_hour_utc(timezone.now() if now is None else now)
    return tuple(current - timedelta(hours=offset) for offset in range(OPEN_HOUR_WINDOW))


def truncate_hour_utc(moment: datetime) -> datetime:
    if timezone.is_naive(moment):
        message = "用量时间必须带时区。"
        raise ValueError(message)
    utc = moment.astimezone(UTC)
    return utc.replace(minute=0, second=0, microsecond=0)


def flush_counters() -> int:
    flushed = 0
    for hour_start in open_hour_starts():
        flushed += _flush_hour(hour_start)
    return flushed


def _decide(spec: UsageCategory) -> bool:
    module = importlib.import_module("easyauth.usage.enforcement")
    decide_obj = cast("object", getattr(module, "decide", None))
    if not callable(decide_obj):
        message = "easyauth.usage.enforcement.decide 必须可调用。"
        raise TypeError(message)
    result = decide_obj(spec)
    if not isinstance(result, bool):
        message = "easyauth.usage.enforcement.decide 必须返回 bool。"
        raise TypeError(message)
    return result


def _refuse(spec: UsageCategory) -> None:
    hour_start = truncate_hour_utc(timezone.now())
    _ = _try_incr(_counter_key(hour_start, spec.key, _COUNTER_KIND_BLOCKED))
    detail = f"category={spec.key}, metric={spec.metric}, priority={spec.priority}"
    message = f"用量策略拒绝本次钉钉调用({detail})。"
    raise DingTalkCallBudgetExceededError(message)


def _increment_allowed(spec: UsageCategory) -> None:
    now = timezone.now()
    hour_start = truncate_hour_utc(now)
    if not _try_incr(_counter_key(hour_start, spec.key, _COUNTER_KIND_COUNT)):
        return
    if spec.metric != "api" or not spec.billed:
        return
    day_key = _day_billed_key(timezone.localtime(now).date())
    _ = _try_incr(day_key)


def _flush_hour(hour_start: datetime) -> int:
    flushed = 0
    counts = cached_hour_counts(hour_start)
    for key, spec in CATEGORIES.items():
        pair = counts.get(key, (0, 0))
        if pair[0] == 0 and pair[1] == 0:
            continue
        _upsert_bucket(hour_start, spec, count=pair[0], blocked=pair[1])
        flushed += 1
    return flushed


def _upsert_bucket(
    hour_start: datetime,
    spec: UsageCategory,
    *,
    count: int,
    blocked: int,
) -> None:
    updated = _raise_bucket_to(hour_start, spec.key, count=count, blocked=blocked)
    if updated:
        return
    try:
        _ = UsageBucket.objects.create(
            hour_start=hour_start,
            source=SOURCE_EASYAUTH,
            category=spec.key,
            metric=spec.metric,
            billed=spec.billed,
            count=count,
            blocked_count=blocked,
        )
    except IntegrityError:
        _ = _raise_bucket_to(hour_start, spec.key, count=count, blocked=blocked)


def _raise_bucket_to(hour_start: datetime, category_key: str, *, count: int, blocked: int) -> int:
    return UsageBucket.objects.filter(
        hour_start=hour_start,
        source=SOURCE_EASYAUTH,
        category=category_key,
    ).update(
        count=Greatest(F("count"), Value(count)),
        blocked_count=Greatest(F("blocked_count"), Value(blocked)),
        updated_at=timezone.now(),
    )


def _read_hour_counts(hour_start: datetime) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for key in CATEGORIES:
        count = _read_count(_counter_key(hour_start, key, _COUNTER_KIND_COUNT))
        blocked = _read_count(_counter_key(hour_start, key, _COUNTER_KIND_BLOCKED))
        if count == 0 and blocked == 0:
            continue
        result[key] = (count, blocked)
    return result


def _counter_key(hour_start: datetime, category_key: str, kind: _CounterKind) -> str:
    stamp = truncate_hour_utc(hour_start).strftime("%Y%m%d%H")
    return f"usage:{stamp}:{category_key}:{kind}"


def _day_billed_key(day: date) -> str:
    return f"usage:day:{day.strftime('%Y%m%d')}:api_billed"


def _read_count(key: str) -> int:
    value = cast("object", cache.get(key))
    if value is None:
        return 0
    return _as_count(value)


def _try_incr(key: str, delta: int = 1) -> bool:
    try:
        _ = _incr(key, delta)
    except _CACHE_BACKEND_ERRORS as error:
        _warn_cache_failure(error)
        return False
    return True


def _incr(key: str, delta: int) -> int:
    try:
        return _as_count(cast("object", cache.incr(key, delta)))
    except ValueError:
        _ = cache.add(key, 0, timeout=COUNTER_TTL_SECONDS)
        try:
            return _as_count(cast("object", cache.incr(key, delta)))
        except ValueError as error:
            message = "用量计数缓存无法递增。"
            raise _CacheMeteringError(message) from error


def _as_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        message = "用量计数缓存值非法。"
        raise _CacheMeteringError(message)
    return value


def _warn_cache_failure(error: BaseException) -> None:
    now = timezone.now().timestamp()
    if now - _CACHE_WARN_GATE.last_at < CACHE_WARNING_INTERVAL_SECONDS:
        return
    _CACHE_WARN_GATE.last_at = now
    logger.warning("用量计数缓存失败, 放行本次调用: %s", error)
