from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Final, Literal, cast

from django.utils import timezone

from easyauth.api.datetime_json import datetime_value

if TYPE_CHECKING:
    from easyauth.usage.config import QuotaMetric
    from easyauth.usage.models import JsonValue

type EnforcementStateName = Literal[
    "normal",
    "degraded_p2",
    "degraded_p1",
    "throttled",
    "blocked",
    "stream_paused",
]
type LimitReason = Literal["daily_cap", "monthly_quota"] | None
type StreamTransition = Literal["paused", "resumed"] | None
type ApiPolicy = Literal["alert_only", "degrade", "throttle", "block_all"]

QUOTA_METRICS: Final[tuple[QuotaMetric, ...]] = ("api", "webhook", "stream")
ENFORCEMENT_STATE_NAMES: Final[tuple[EnforcementStateName, ...]] = (
    "normal",
    "degraded_p2",
    "degraded_p1",
    "throttled",
    "blocked",
    "stream_paused",
)
LIMIT_REASONS: Final[tuple[Literal["daily_cap", "monthly_quota"], ...]] = (
    "daily_cap",
    "monthly_quota",
)
DEFAULT_THROTTLE_P1: Final = 200
DEFAULT_THROTTLE_P2: Final = 20
ENFORCEMENT_INVALID_MESSAGE: Final = "enforcement 缓存文档非法。"
OVER_CAP_POLICIES: Final[tuple[ApiPolicy, ...]] = (
    "alert_only",
    "degrade",
    "throttle",
    "block_all",
)


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


def enforcement_payload(state: EnforcementState) -> dict[str, JsonValue]:
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
        "throttle_per_hour": cast(
            "JsonValue",
            {"p1": state.api_throttle_p1, "p2": state.api_throttle_p2},
        ),
    }


def parse_enforcement_state(raw: object) -> EnforcementState | None:
    if not isinstance(raw, dict):
        return None
    try:
        return _state_from_mapping(cast("dict[object, object]", raw))
    except (TypeError, ValueError):
        return None


def resumed_enforcement_payload(raw: object, period: str) -> dict[str, JsonValue]:
    now = timezone.now()
    state = parse_enforcement_state(raw)
    metrics = {} if state is None else dict(state.metrics)
    metrics["stream"] = MetricEnforcement(
        metric="stream",
        state="normal",
        reason=None,
        since=None,
    )
    base = EnforcementState(metrics=metrics, evaluated_at=now) if state is None else state
    return enforcement_payload(
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
        _as_member(raw.get("api_over_limit_policy"), OVER_CAP_POLICIES),
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
