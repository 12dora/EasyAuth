from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, Literal, cast, override

from django.core.cache import cache
from django.utils import timezone
from redis.exceptions import RedisError

from easyauth.api.datetime_json import datetime_value
from easyauth.usage.config import ApiMetricConfig, QuotaMetric, UsageConfig, load
from easyauth.usage.models import UsageRuntimeState
from easyauth.usage.queries import day_period_key, month_period_key, used_this_month, used_today

if TYPE_CHECKING:
    from easyauth.usage.models import JsonValue
    from easyauth.usage.registry import UsageCategory, UsagePriority

type EnforcementStateName = Literal[
    "normal", "degraded_p2", "degraded_p1", "throttled", "blocked", "stream_paused"
]
type LimitReason = Literal["daily_cap", "monthly_quota"] | None
type StreamTransition = Literal["paused", "resumed"] | None
type ApiPolicy = Literal["alert_only", "degrade", "throttle", "block_all"]

ENFORCEMENT_CACHE_KEY: Final = "usage:enforcement"
ENFORCEMENT_CACHE_TTL_SECONDS: Final = 300
USAGE_RUNTIME_PK: Final = 1
THROTTLE_TTL_SECONDS: Final = 3 * 60 * 60
AUTHENTIK_POLICY_TTL: Final = timedelta(minutes=10)
QUOTA_METRICS: Final[tuple[QuotaMetric, ...]] = ("api", "webhook", "stream")
ENFORCEMENT_STATE_NAMES: Final[tuple[EnforcementStateName, ...]] = (
    "normal", "degraded_p2", "degraded_p1", "throttled", "blocked", "stream_paused",
)
LIMIT_REASONS: Final[tuple[Literal["daily_cap", "monthly_quota"], ...]] = (
    "daily_cap", "monthly_quota",
)
OVER_CAP_STATE: Final[dict[ApiPolicy, EnforcementStateName]] = {
    "alert_only": "normal",
    "degrade": "degraded_p2",
    "throttle": "throttled",
    "block_all": "blocked",
}
STREAM_NOT_PAUSED_MESSAGE: Final = "Stream 当前未暂停, 不能恢复。"
NAIVE_DATETIME_MESSAGE: Final = "evaluate 需要带时区的 datetime。"
CACHE_INCR_FAILED_MESSAGE: Final = "用量节流计数缓存无法递增。"
ENFORCEMENT_INVALID_MESSAGE: Final = "enforcement 缓存文档非法。"
DEFAULT_THROTTLE_P1: Final = 200
DEFAULT_THROTTLE_P2: Final = 20

_CACHE_BACKEND_ERRORS: Final = (
    OSError, ConnectionError, TimeoutError, NotImplementedError, RedisError,
)


class StreamNotPausedError(Exception):
    @override
    def __str__(self) -> str:
        return STREAM_NOT_PAUSED_MESSAGE


class _CacheMeteringError(Exception):
    pass


_THROTTLE_ERRORS: Final = (*_CACHE_BACKEND_ERRORS, _CacheMeteringError)


@dataclass(frozen=True, slots=True)
class MetricEnforcement:
    metric: QuotaMetric
    state: EnforcementStateName
    reason: LimitReason
    since: datetime | None


@dataclass(frozen=True, slots=True)
class EnforcementState:
    metrics: dict[str, MetricEnforcement]
    evaluated_at: datetime
    stream_paused: bool = False
    stream_paused_at: datetime | None = None
    stream_paused_period: str = ""
    stream_manual_resume_period: str = ""
    stream_transition: StreamTransition = None
    api_daily_cap: int | None = None
    api_over_limit_policy: ApiPolicy = "degrade"
    api_throttle_p1: int = DEFAULT_THROTTLE_P1
    api_throttle_p2: int = DEFAULT_THROTTLE_P2


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


def evaluate(now: datetime) -> EnforcementState:
    if timezone.is_naive(now):
        raise ValueError(NAIVE_DATETIME_MESSAGE)
    config = load()
    day: dict[QuotaMetric, int] = {metric: used_today(metric) for metric in QUOTA_METRICS}
    month: dict[QuotaMetric, int] = {metric: used_this_month(metric) for metric in QUOTA_METRICS}
    state = _compute_state(config, day, month, now, _load_runtime())
    _persist(state)
    return state


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


def stream_should_run() -> bool:
    cached = _cached_enforcement()
    if cached is not None:
        return not cached.stream_paused
    row = UsageRuntimeState.objects.filter(pk=USAGE_RUNTIME_PK).first()
    if row is None:
        return True
    return not row.stream_paused


def resume_stream(actor: object) -> None:
    _ = actor
    row = UsageRuntimeState.objects.filter(pk=USAGE_RUNTIME_PK).first()
    if row is None or not row.stream_paused:
        raise StreamNotPausedError(STREAM_NOT_PAUSED_MESSAGE)
    period = row.stream_paused_period
    row.stream_paused = False
    row.stream_paused_at = None
    row.stream_manual_resume_period = period
    row.enforcement = _resumed_payload(cast("object", row.enforcement), period)
    fields = ["stream_paused", "stream_paused_at", "stream_manual_resume_period", "enforcement"]
    row.save(update_fields=fields)
    cache.set(ENFORCEMENT_CACHE_KEY, row.enforcement, ENFORCEMENT_CACHE_TTL_SECONDS)


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


def _persist(state: EnforcementState) -> None:
    payload = _enforcement_payload(state)
    row = UsageRuntimeState.objects.filter(pk=USAGE_RUNTIME_PK).first()
    if row is None:
        row = UsageRuntimeState(pk=USAGE_RUNTIME_PK)
        row.authentik_error = ""
    row.enforcement = payload
    row.evaluated_at = state.evaluated_at
    row.stream_paused = state.stream_paused
    row.stream_paused_at = state.stream_paused_at
    row.stream_paused_period = state.stream_paused_period
    row.stream_manual_resume_period = state.stream_manual_resume_period
    row.save()
    cache.set(ENFORCEMENT_CACHE_KEY, payload, ENFORCEMENT_CACHE_TTL_SECONDS)


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
    return _parse_state(cast("object", cache.get(ENFORCEMENT_CACHE_KEY)))


def _load_runtime() -> _RuntimeSnapshot:
    row = UsageRuntimeState.objects.filter(pk=USAGE_RUNTIME_PK).first()
    if row is None:
        return _RuntimeSnapshot(
            metrics={}, stream_paused=False, stream_paused_at=None,
            stream_paused_period="", stream_manual_resume_period="",
        )
    parsed = _parse_state(cast("object", row.enforcement))
    return _RuntimeSnapshot(
        metrics={} if parsed is None else parsed.metrics,
        stream_paused=row.stream_paused,
        stream_paused_at=row.stream_paused_at,
        stream_paused_period=row.stream_paused_period,
        stream_manual_resume_period=row.stream_manual_resume_period,
    )


def _enforcement_payload(state: EnforcementState) -> dict[str, JsonValue]:
    metrics: dict[str, JsonValue] = {
        key: cast(
            "JsonValue",
            {
                "metric": item.metric,
                "state": item.state,
                "reason": item.reason,
                "since": datetime_value(item.since),
            },
        )
        for key, item in state.metrics.items()
    }
    return {
        "metrics": metrics,
        "evaluated_at": datetime_value(state.evaluated_at),
        "stream_paused": state.stream_paused,
        "stream_paused_at": datetime_value(state.stream_paused_at),
        "stream_paused_period": state.stream_paused_period,
        "stream_manual_resume_period": state.stream_manual_resume_period,
        "api_daily_cap": state.api_daily_cap,
        "api_over_limit_policy": state.api_over_limit_policy,
        "throttle_per_hour": cast("JsonValue", {
            "p1": state.api_throttle_p1, "p2": state.api_throttle_p2,
        }),
    }


def _parse_state(raw: object) -> EnforcementState | None:
    if not isinstance(raw, dict):
        return None
    try:
        return _state_from_mapping(cast("dict[object, object]", raw))
    except (TypeError, ValueError):
        return None


def _state_from_mapping(raw: dict[object, object]) -> EnforcementState:
    metrics_raw = raw.get("metrics")
    evaluated = _parse_datetime(raw.get("evaluated_at"))
    if not isinstance(metrics_raw, dict) or evaluated is None:
        raise ValueError(ENFORCEMENT_INVALID_MESSAGE)
    metrics_map = cast("dict[object, object]", metrics_raw)
    metrics: dict[str, MetricEnforcement] = {}
    for key, value in metrics_map.items():
        item = _parse_metric(value)
        if item is not None and key in QUOTA_METRICS:
            metrics[item.metric] = item
    paused_raw = raw.get("stream_paused_period")
    resume_raw = raw.get("stream_manual_resume_period")
    policy = cast(
        "ApiPolicy | None",
        _as_member(raw.get("api_over_limit_policy"), tuple(OVER_CAP_STATE)),
    )
    p1, p2 = _throttle_pair(raw.get("throttle_per_hour"))
    return EnforcementState(
        metrics=metrics,
        evaluated_at=evaluated,
        stream_paused=raw.get("stream_paused") is True,
        stream_paused_at=_parse_datetime(raw.get("stream_paused_at")),
        stream_paused_period=paused_raw if isinstance(paused_raw, str) else "",
        stream_manual_resume_period=resume_raw if isinstance(resume_raw, str) else "",
        api_daily_cap=_optional_int(raw.get("api_daily_cap"), minimum=1),
        api_over_limit_policy="degrade" if policy is None else policy,
        api_throttle_p1=p1,
        api_throttle_p2=p2,
    )


def _parse_metric(raw: object) -> MetricEnforcement | None:
    if not isinstance(raw, dict):
        return None
    mapping = cast("dict[object, object]", raw)
    metric = cast("QuotaMetric | None", _as_member(mapping.get("metric"), QUOTA_METRICS))
    state = cast(
        "EnforcementStateName | None",
        _as_member(mapping.get("state"), ENFORCEMENT_STATE_NAMES),
    )
    if metric is None or state is None:
        return None
    return MetricEnforcement(
        metric=metric,
        state=state,
        reason=_as_member(mapping.get("reason"), LIMIT_REASONS),
        since=_parse_datetime(mapping.get("since")),
    )


def _as_member[T](value: object, options: tuple[T, ...]) -> T | None:
    for name in options:
        if value == name:
            return name
    return None


def _throttle_pair(raw: object) -> tuple[int, int]:
    if raw is None:
        return DEFAULT_THROTTLE_P1, DEFAULT_THROTTLE_P2
    mapping = cast("dict[object, object]", raw) if isinstance(raw, dict) else {}
    p1 = _optional_int(mapping.get("p1"), minimum=0)
    p2 = _optional_int(mapping.get("p2"), minimum=0)
    if p1 is None or p2 is None:
        raise ValueError(ENFORCEMENT_INVALID_MESSAGE)
    return p1, p2


def _optional_int(value: object, *, minimum: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(ENFORCEMENT_INVALID_MESSAGE)
    return value


def _parse_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value
    if not isinstance(value, str):
        return None
    parsed = datetime.fromisoformat(value)
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _resumed_payload(raw: object, period: str) -> dict[str, JsonValue]:
    now = timezone.now()
    state = _parse_state(raw)
    metrics = {} if state is None else dict(state.metrics)
    metrics["stream"] = _metric("stream", "normal", None, now, metrics.get("stream"))
    base = EnforcementState(metrics=metrics, evaluated_at=now) if state is None else state
    return _enforcement_payload(
        replace(
            base,
            metrics=metrics,
            stream_paused=False,
            stream_paused_at=None,
            stream_paused_period=period,
            stream_manual_resume_period=period,
            stream_transition=None,
        ),
    )
