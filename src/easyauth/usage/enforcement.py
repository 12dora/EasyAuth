from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, cast, override

from django.core.cache import cache
from django.db import DatabaseError, transaction
from django.utils import timezone
from redis.exceptions import RedisError

from easyauth.api.datetime_json import datetime_value
from easyauth.usage.config import load
from easyauth.usage.enforcement_state import (
    QUOTA_METRICS,
    EnforcementState,
    MetricEnforcement,
    enforcement_payload,
    parse_enforcement_state,
    resumed_enforcement_payload,
)
from easyauth.usage.models import UsageRuntimeState
from easyauth.usage.queries import day_period_key, month_period_key, used_this_month, used_today

if TYPE_CHECKING:
    from collections.abc import Callable

    from easyauth.usage.config import ApiMetricConfig, QuotaMetric, UsageConfig
    from easyauth.usage.enforcement_state import (
        ApiPolicy,
        EnforcementStateName,
        LimitReason,
        StreamTransition,
    )
    from easyauth.usage.models import JsonValue
    from easyauth.usage.registry import UsageCategory, UsagePriority

logger = logging.getLogger(__name__)

ENFORCEMENT_CACHE_KEY: Final = "usage:enforcement"
ENFORCEMENT_CACHE_TTL_SECONDS: Final = 300
USAGE_RUNTIME_PK: Final = 1
THROTTLE_TTL_SECONDS: Final = 3 * 60 * 60
AUTHENTIK_POLICY_TTL: Final = timedelta(minutes=10)
STREAM_LOOKUP_WARN_INTERVAL_SECONDS: Final = 60.0
STREAM_NOT_PAUSED_MESSAGE: Final = "Stream 当前未暂停, 不能恢复。"
NAIVE_DATETIME_MESSAGE: Final = "evaluate 需要带时区的 datetime。"
CACHE_INCR_FAILED_MESSAGE: Final = "用量节流计数缓存无法递增。"
STREAM_RESUMED_CALLABLE_MESSAGE: Final = (
    "easyauth.usage.alerts.record_stream_resumed 必须可调用。"
)
EVALUATE_UPDATE_FIELDS: Final[tuple[str, ...]] = (
    "enforcement",
    "evaluated_at",
    "stream_paused",
    "stream_paused_at",
    "stream_paused_period",
)
RESUME_UPDATE_FIELDS: Final[tuple[str, ...]] = (
    "stream_paused",
    "stream_paused_at",
    "stream_paused_period",
    "stream_manual_resume_period",
)
STREAM_DECISION_FIELDS: Final[tuple[str, ...]] = (
    "enforcement",
    "stream_paused",
    "stream_paused_at",
    "stream_paused_period",
    "stream_manual_resume_period",
)
OVER_CAP_STATE: Final[dict[ApiPolicy, EnforcementStateName]] = {
    "alert_only": "normal",
    "degrade": "degraded_p2",
    "throttle": "throttled",
    "block_all": "blocked",
}

_CACHE_BACKEND_ERRORS: Final = (
    OSError,
    ConnectionError,
    TimeoutError,
    NotImplementedError,
    RedisError,
)


class StreamNotPausedError(Exception):
    @override
    def __str__(self) -> str:
        return STREAM_NOT_PAUSED_MESSAGE


class _CacheMeteringError(Exception):
    pass


_THROTTLE_ERRORS: Final = (*_CACHE_BACKEND_ERRORS, _CacheMeteringError)


@dataclass(frozen=True, slots=True)
class _RuntimeSnapshot:
    metrics: dict[str, MetricEnforcement]
    stream_paused: bool
    stream_paused_at: datetime | None
    stream_paused_period: str
    stream_manual_resume_period: str


@dataclass(frozen=True, slots=True)
class _StreamPlan:
    paused: bool
    paused_at: datetime | None
    paused_period: str
    manual_resume_period: str
    transition: StreamTransition


@dataclass(frozen=True, slots=True)
class _UsageTotals:
    day: dict[QuotaMetric, int]
    month: dict[QuotaMetric, int]


@dataclass(slots=True)
class _StreamRunMemo:
    allow: bool = True


@dataclass(slots=True)
class _WarnGate:
    last_at: float = 0.0


_STREAM_RUN_MEMO = _StreamRunMemo()
_STREAM_WARN_GATE = _WarnGate()


def evaluate(now: datetime) -> EnforcementState:
    if timezone.is_naive(now):
        raise ValueError(NAIVE_DATETIME_MESSAGE)
    return _commit_evaluation(load(), _usage_totals(), now)


def decide(category: UsageCategory) -> bool:
    if not category.billed:
        return True
    try:
        return _decide_billed(category)
    except _CACHE_BACKEND_ERRORS:
        return True


def authentik_policy(state: EnforcementState) -> dict[str, object]:
    api = state.metrics.get("api")
    name: EnforcementStateName = "normal" if api is None else api.state
    blocked: list[str] = []
    if name == "degraded_p2":
        blocked = ["p2"]
    elif name in {"degraded_p1", "blocked"}:
        blocked = ["p1", "p2"]
    throttle: dict[str, int | None] = {"p1": None, "p2": None}
    if name == "throttled":
        limits = load().api.throttle_per_hour
        throttle = {"p1": limits.p1, "p2": limits.p2}
    expires = (timezone.now() + AUTHENTIK_POLICY_TTL).astimezone(UTC)
    return {
        "blocked_priorities": blocked,
        "throttle_per_hour": throttle,
        "block_p0_billed": name == "blocked",
        "expires_at": datetime_value(expires).replace("+00:00", "Z"),
    }


# 监管循环不能因缓存或数据库抖动退出; 失败时沿用本进程上一次决策。
def stream_should_run() -> bool:
    try:
        decision, cache_error = _read_stream_should_run()
    except DatabaseError as error:
        _warn_stream_limited(
            "用量执行状态读取失败, 沿用本进程最近一次 Stream 决策: %s",
            error,
        )
        return _STREAM_RUN_MEMO.allow
    if cache_error is not None:
        _warn_stream_limited("用量执行状态缓存读取失败, 改读数据库: %s", cache_error)
    _STREAM_RUN_MEMO.allow = decision
    return decision


def resume_stream(actor: object) -> None:
    _ = actor
    now = timezone.now()
    with transaction.atomic():
        row = _require_paused_row()
        period = row.stream_paused_period
        payload = resumed_enforcement_payload(row.enforcement, period)
        _mark_resumed(row, period)
        _emit_stream_resumed(now, period)
    cache.set(ENFORCEMENT_CACHE_KEY, payload, ENFORCEMENT_CACHE_TTL_SECONDS)


def _usage_totals() -> _UsageTotals:
    return _UsageTotals(
        day={metric: used_today(metric) for metric in QUOTA_METRICS},
        month={metric: used_this_month(metric) for metric in QUOTA_METRICS},
    )


def _commit_evaluation(
    config: UsageConfig,
    usage: _UsageTotals,
    now: datetime,
) -> EnforcementState:
    with transaction.atomic():
        row = _lock_runtime()
        # 暂停判定只认锁内重新读到的手动恢复周期, 避免覆盖并发恢复。
        row.refresh_from_db(fields=STREAM_DECISION_FIELDS)
        state = _compute_state(config, usage.day, usage.month, now, _snapshot(row))
        payload = _write_evaluation(row, state)
    cache.set(ENFORCEMENT_CACHE_KEY, payload, ENFORCEMENT_CACHE_TTL_SECONDS)
    return state


def _lock_runtime() -> UsageRuntimeState:
    row, _created = UsageRuntimeState.objects.select_for_update().get_or_create(
        pk=USAGE_RUNTIME_PK,
    )
    return row


def _write_evaluation(row: UsageRuntimeState, state: EnforcementState) -> dict[str, JsonValue]:
    payload = enforcement_payload(state)
    row.enforcement = payload
    row.evaluated_at = state.evaluated_at
    row.stream_paused = state.stream_paused
    row.stream_paused_at = state.stream_paused_at
    row.stream_paused_period = state.stream_paused_period
    row.save(update_fields=EVALUATE_UPDATE_FIELDS)
    return payload


def _require_paused_row() -> UsageRuntimeState:
    row = (
        UsageRuntimeState.objects.select_for_update()
        .filter(pk=USAGE_RUNTIME_PK)
        .first()
    )
    if row is None or not row.stream_paused:
        raise StreamNotPausedError(STREAM_NOT_PAUSED_MESSAGE)
    return row


def _mark_resumed(row: UsageRuntimeState, period: str) -> None:
    row.stream_paused = False
    row.stream_paused_at = None
    row.stream_paused_period = period
    row.stream_manual_resume_period = period
    row.save(update_fields=RESUME_UPDATE_FIELDS)


def _emit_stream_resumed(now: datetime, period_key: str) -> None:
    module = importlib.import_module("easyauth.usage.alerts")
    record_obj = cast("object", getattr(module, "record_stream_resumed", None))
    if not callable(record_obj):
        raise TypeError(STREAM_RESUMED_CALLABLE_MESSAGE)
    record = cast("Callable[[datetime, str], object]", record_obj)
    _ = record(now, period_key)


def _read_stream_should_run() -> tuple[bool, BaseException | None]:
    try:
        state = _cached_enforcement()
    except _CACHE_BACKEND_ERRORS as error:
        return _db_stream_should_run(), error
    if state is None:
        return _db_stream_should_run(), None
    return (not state.stream_paused), None


def _db_stream_should_run() -> bool:
    row = UsageRuntimeState.objects.filter(pk=USAGE_RUNTIME_PK).first()
    if row is None:
        return True
    return not row.stream_paused


def _warn_stream_limited(template: str, error: BaseException) -> None:
    now = timezone.now().timestamp()
    if now - _STREAM_WARN_GATE.last_at < STREAM_LOOKUP_WARN_INTERVAL_SECONDS:
        return
    _STREAM_WARN_GATE.last_at = now
    logger.warning(template, error)


def _compute_state(
    config: UsageConfig,
    day: dict[QuotaMetric, int],
    month: dict[QuotaMetric, int],
    now: datetime,
    runtime: _RuntimeSnapshot,
) -> EnforcementState:
    stream_reason = _limit_reason(config, "stream", day, month)
    plan = _plan_stream(config, stream_reason, now, runtime)
    api = _api_enforcement(config, day, month, now, runtime.metrics.get("api"))
    webhook = _metric("webhook", "normal", None, now, runtime.metrics.get("webhook"))
    stream = _metric(
        "stream",
        "stream_paused" if plan.paused else "normal",
        stream_reason if plan.paused else None,
        now,
        runtime.metrics.get("stream"),
    )
    api_cfg = config.api
    return EnforcementState(
        metrics={"api": api, "webhook": webhook, "stream": stream},
        evaluated_at=now,
        stream_paused=plan.paused,
        stream_paused_at=plan.paused_at,
        stream_paused_period=plan.paused_period,
        stream_manual_resume_period=plan.manual_resume_period,
        stream_transition=plan.transition,
        api_daily_cap=api_cfg.daily_cap,
        api_over_limit_policy=api_cfg.over_limit_policy,
        api_throttle_p1=api_cfg.throttle_per_hour.p1,
        api_throttle_p2=api_cfg.throttle_per_hour.p2,
    )


def _api_enforcement(
    config: UsageConfig,
    day: dict[QuotaMetric, int],
    month: dict[QuotaMetric, int],
    now: datetime,
    previous: MetricEnforcement | None,
) -> MetricEnforcement:
    reason = _limit_reason(config, "api", day, month)
    state = _api_state_name(config.api, month["api"], reason)
    effect: LimitReason = None if state == "normal" else reason
    if state == "degraded_p1":
        effect = "monthly_quota"
    return _metric("api", state, effect, now, previous)


def _api_state_name(
    config: ApiMetricConfig,
    used_month: int,
    reason: LimitReason,
) -> EnforcementStateName:
    if reason is None or config.over_limit_policy == "alert_only":
        return "normal"
    if config.over_limit_policy == "block_all":
        return "blocked"
    if config.over_limit_policy == "throttle":
        return "throttled"
    quota = config.monthly_quota
    if quota is not None and used_month * 100 >= quota * config.degrade_escalation_percent:
        return "degraded_p1"
    return "degraded_p2"


def _metric(
    metric: QuotaMetric,
    state: EnforcementStateName,
    reason: LimitReason,
    now: datetime,
    previous: MetricEnforcement | None,
) -> MetricEnforcement:
    return MetricEnforcement(
        metric=metric,
        state=state,
        reason=reason,
        since=_preserved_since(previous, state, now),
    )


def _plan_stream(
    config: UsageConfig,
    reason: LimitReason,
    now: datetime,
    runtime: _RuntimeSnapshot,
) -> _StreamPlan:
    period = _period_for_reason(reason, now)
    should_pause = (
        config.stream.over_limit_policy == "pause_stream"
        and reason is not None
        and runtime.stream_manual_resume_period != period
    )
    if not should_pause:
        return _StreamPlan(
            paused=False,
            paused_at=None,
            paused_period=runtime.stream_paused_period,
            manual_resume_period=runtime.stream_manual_resume_period,
            transition="resumed" if runtime.stream_paused else None,
        )
    same_period = runtime.stream_paused and runtime.stream_paused_period == period
    return _StreamPlan(
        paused=True,
        paused_at=runtime.stream_paused_at or now if same_period else now,
        paused_period=period,
        manual_resume_period=runtime.stream_manual_resume_period,
        transition=None if same_period else "paused",
    )


def _limit_reason(
    config: UsageConfig,
    metric: QuotaMetric,
    day: dict[QuotaMetric, int],
    month: dict[QuotaMetric, int],
) -> LimitReason:
    quota = config.quota_for(metric)
    if quota.monthly_quota is not None and month[metric] >= quota.monthly_quota:
        return "monthly_quota"
    if quota.daily_cap is not None and day[metric] >= quota.daily_cap:
        return "daily_cap"
    return None


def _period_for_reason(reason: LimitReason, now: datetime) -> str:
    if reason == "monthly_quota":
        return month_period_key(now)
    if reason == "daily_cap":
        return day_period_key(now)
    return ""


def _preserved_since(
    previous: MetricEnforcement | None,
    state: EnforcementStateName,
    now: datetime,
) -> datetime | None:
    if state == "normal":
        return None
    if previous is not None and previous.state == state and previous.since is not None:
        return previous.since
    return now


def _snapshot(row: UsageRuntimeState) -> _RuntimeSnapshot:
    parsed = parse_enforcement_state(row.enforcement)
    return _RuntimeSnapshot(
        metrics={} if parsed is None else parsed.metrics,
        stream_paused=row.stream_paused,
        stream_paused_at=row.stream_paused_at,
        stream_paused_period=row.stream_paused_period,
        stream_manual_resume_period=row.stream_manual_resume_period,
    )


def _decide_billed(category: UsageCategory) -> bool:
    cached = _cached_enforcement()
    if cached is None:
        return True
    item = cached.metrics.get(category.metric)
    name: EnforcementStateName = "normal" if item is None else item.state
    if category.metric == "api":
        name = _apply_realtime(name, cached, timezone.now())
    return _allow_priority(category.priority, name, cached)


def _apply_realtime(
    name: EnforcementStateName,
    state: EnforcementState,
    now: datetime,
) -> EnforcementStateName:
    if name != "normal":
        return name
    billed = _read_api_billed_today(now)
    cap = state.api_daily_cap
    if billed is None or cap is None or billed < cap:
        return "normal"
    return OVER_CAP_STATE[state.api_over_limit_policy]


def _allow_priority(
    priority: UsagePriority | None,
    name: EnforcementStateName,
    state: EnforcementState,
) -> bool:
    if priority is None or name in {"normal", "stream_paused"}:
        return True
    if name == "degraded_p2":
        return priority != "p2"
    if name == "degraded_p1":
        return priority == "p0"
    if name == "blocked":
        return False
    if name == "throttled":
        return _throttle_allow(priority, state, timezone.now())
    return True


def _throttle_allow(priority: UsagePriority, state: EnforcementState, now: datetime) -> bool:
    if priority == "p0":
        return True
    limit = state.api_throttle_p1 if priority == "p1" else state.api_throttle_p2
    count = _incr_throttle(now, priority)
    if count is None:
        return True
    return count <= limit


def _read_api_billed_today(now: datetime) -> int | None:
    stamp = timezone.localtime(now).strftime("%Y%m%d")
    local = _cache_int(f"usage:day:{stamp}:api_billed")
    if local is None:
        return None
    authentik = _cache_int(f"usage:day:{stamp}:api_billed_authentik")
    extra = 0 if authentik is None else authentik
    return local + extra


def _incr_throttle(now: datetime, priority: UsagePriority) -> int | None:
    hour = now.astimezone(UTC).strftime("%Y%m%d%H")
    key = f"usage:throttle:{hour}:{priority}"
    try:
        return _incr(key)
    except _THROTTLE_ERRORS:
        return None


def _incr(key: str) -> int:
    try:
        return _as_count(cache.incr(key))
    except ValueError:
        _ = cache.add(key, 0, timeout=THROTTLE_TTL_SECONDS)
        try:
            return _as_count(cache.incr(key))
        except ValueError as error:
            raise _CacheMeteringError(CACHE_INCR_FAILED_MESSAGE) from error


def _as_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _CacheMeteringError(CACHE_INCR_FAILED_MESSAGE)
    return value


def _cache_int(key: str) -> int | None:
    value = cast("object", cache.get(key))
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _cached_enforcement() -> EnforcementState | None:
    return parse_enforcement_state(cast("object", cache.get(ENFORCEMENT_CACHE_KEY)))
