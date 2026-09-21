from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Literal, cast
from zoneinfo import ZoneInfo

from django.utils import timezone

from easyauth.admin_console.api_responses import error_response
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode
from easyauth.usage import alerts, queries
from easyauth.usage.config import UsageConfig
from easyauth.usage.config import load as load_usage_config
from easyauth.usage.models import UsageAlertEvent, UsageRuntimeState
from easyauth.usage.registry import UsageMetric
from easyauth.usage.registry import category as usage_category

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from django.http import JsonResponse, QueryDict

    from easyauth.api.errors import JsonValue
    from easyauth.usage.config import MetricQuotaConfig
    from easyauth.usage.queries import UsageCategoryTotal, UsageSeriesPoint

USAGE_SINGLETON_ID: Final = 1
MAX_USAGE_RANGE_DAYS: Final = 400
HOUR_GRANULARITY_MAX_DAYS: Final = 2
DEFAULT_ALERT_LIMIT: Final = 50
MAX_ALERT_LIMIT: Final = 200
AUTHENTIK_STALE_AFTER: Final = timedelta(minutes=10)
SUMMARY_METRICS: Final[tuple[UsageMetric, ...]] = ("api", "webhook", "stream")
ENFORCEMENT_STATES: Final[frozenset[str]] = frozenset(
    {"normal", "degraded_p2", "degraded_p1", "throttled", "blocked", "stream_paused"},
)
LIMIT_REASONS: Final[frozenset[str]] = frozenset({"daily_cap", "monthly_quota"})
DATE_PATTERN: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RANGE_REQUIRED_MESSAGE: Final = "from 与 to 必须为 YYYY-MM-DD。"
RANGE_FORMAT_MESSAGE: Final = "日期必须为 YYYY-MM-DD。"
RANGE_ORDER_MESSAGE: Final = "from 不能晚于 to。"
RANGE_TOO_LONG_MESSAGE: Final = "查询区间不能超过 400 天。"
GRANULARITY_INVALID_MESSAGE: Final = "granularity 必须为 hour 或 day。"
LIMIT_INVALID_MESSAGE: Final = "limit 必须为 1 到 200 的整数。"
NEGATIVE_UNBILLED_MESSAGE: Final = "api 未计费用量不能为负。"
ENFORCEMENT_OBJECT_MESSAGE: Final = "UsageRuntimeState.enforcement 必须是对象。"
ENFORCEMENT_METRIC_OBJECT_MESSAGE: Final = "指标的 enforcement 必须是对象。"
ENFORCEMENT_STATE_MESSAGE: Final = "enforcement.state 无效。"
ENFORCEMENT_REASON_MESSAGE: Final = "enforcement.reason 无效。"
ENFORCEMENT_SINCE_MESSAGE: Final = "enforcement.since 类型无效。"
ZERO_LIMIT_MESSAGE: Final = "用量上限不能为 0。"
INTERNAL_HAS_NO_QUOTA_MESSAGE: Final = "internal 没有配额配置。"

type UsageGranularity = Literal["hour", "day"]


@dataclass(frozen=True, slots=True)
class UsageRange:
    from_date: str
    to_date: str
    start: datetime
    end: datetime
    granularity: UsageGranularity


@dataclass(frozen=True, slots=True)
class MetricUsage:
    used_day: int
    used_month: int
    last_hour: int
    blocked_today: int


def parse_usage_range(query: QueryDict) -> UsageRange | JsonResponse:
    bounds = _parse_date_bounds(query)
    if not isinstance(bounds, tuple):
        return bounds
    from_value, to_value, start, end = bounds
    granularity = _parse_granularity(query, start=start, end=end)
    if not isinstance(granularity, str):
        return granularity
    return UsageRange(
        from_date=from_value,
        to_date=to_value,
        start=start,
        end=end,
        granularity=granularity,
    )


def parse_alert_limit(query: QueryDict) -> int | JsonResponse:
    raw = query.get("limit")
    if raw is None or raw == "":
        return DEFAULT_ALERT_LIMIT
    if not raw.isdigit():
        return _query_error(LIMIT_INVALID_MESSAGE, field="limit", value=raw)
    limit = int(raw)
    if limit < 1 or limit > MAX_ALERT_LIMIT:
        return _query_error(LIMIT_INVALID_MESSAGE, field="limit", value=raw)
    return limit


def summary_payload(*, now: datetime) -> dict[str, JsonValue]:
    config = load_usage_config()
    runtime = _runtime_state()
    day_start, day_end = _local_day_bounds(now)
    enforcement = _enforcement_map(runtime)
    metrics: list[JsonValue] = [
        _metric_summary(
            metric,
            _metric_usage(metric, day_start=day_start, day_end=day_end),
            config=config,
            enforcement=enforcement,
            now=now,
        )
        for metric in SUMMARY_METRICS
    ]
    return {
        "generated_at": datetime_value(now),
        "timezone": _timezone_name(),
        "metrics": metrics,
        "api_breakdown_today": _api_breakdown_today(day_start, day_end),
        "alerts": _alerts_summary(config, now=now),
        "stream": stream_payload(runtime),
        "authentik": _authentik_payload(runtime, now=now),
    }


def timeseries_payload(usage_range: UsageRange) -> dict[str, JsonValue]:
    points = queries.timeseries(usage_range.start, usage_range.end, usage_range.granularity)
    categories = queries.breakdown(usage_range.start, usage_range.end)
    serialized = [_series_point_payload(point) for point in points]
    category_rows = [_category_payload(item) for item in categories]
    return {
        "from": usage_range.from_date,
        "to": usage_range.to_date,
        "granularity": usage_range.granularity,
        "points": _json_object_list(serialized),
        "totals": _series_totals(serialized),
        "categories": _json_object_list(category_rows),
    }


def stream_payload(runtime: UsageRuntimeState | None) -> dict[str, JsonValue]:
    paused = False if runtime is None else runtime.stream_paused
    paused_at = None if runtime is None else datetime_value(runtime.stream_paused_at)
    return {"paused": paused, "paused_at": paused_at, "can_resume": paused}


def _parse_date_bounds(
    query: QueryDict,
) -> tuple[str, str, datetime, datetime] | JsonResponse:
    from_raw = query.get("from")
    to_raw = query.get("to")
    if from_raw is None or from_raw == "" or to_raw is None or to_raw == "":
        return _bad_range(RANGE_REQUIRED_MESSAGE, field="from", value=from_raw)
    from_date = _parse_iso_date(from_raw, field="from")
    if not isinstance(from_date, datetime):
        return from_date
    to_date = _parse_iso_date(to_raw, field="to")
    if not isinstance(to_date, datetime):
        return to_date
    if from_date > to_date:
        return _bad_range(RANGE_ORDER_MESSAGE, field="from", value=from_raw)
    inclusive_days = (to_date.date() - from_date.date()).days + 1
    if inclusive_days > MAX_USAGE_RANGE_DAYS:
        return _bad_range(RANGE_TOO_LONG_MESSAGE, field="to", value=to_raw)
    end = to_date + timedelta(days=1)
    return from_raw, to_raw, from_date, end


def _parse_iso_date(raw: str, *, field: str) -> datetime | JsonResponse:
    if DATE_PATTERN.fullmatch(raw) is None:
        return _bad_range(RANGE_FORMAT_MESSAGE, field=field, value=raw)
    local_date = date.fromisoformat(raw)
    return datetime.combine(local_date, time.min, tzinfo=_local_tz())


def _parse_granularity(
    query: QueryDict,
    *,
    start: datetime,
    end: datetime,
) -> UsageGranularity | JsonResponse:
    raw = query.get("granularity")
    if raw is None or raw == "":
        inclusive_days = (end.date() - start.date()).days
        return "hour" if inclusive_days <= HOUR_GRANULARITY_MAX_DAYS else "day"
    if raw in {"hour", "day"}:
        return cast("UsageGranularity", raw)
    return _bad_range(GRANULARITY_INVALID_MESSAGE, field="granularity", value=raw)


def _metric_usage(metric: UsageMetric, *, day_start: datetime, day_end: datetime) -> MetricUsage:
    blocked = 0
    for item in queries.breakdown(day_start, day_end):
        if item.metric == metric:
            blocked += item.blocked
    return MetricUsage(
        used_day=queries.used_today(metric),
        used_month=queries.used_this_month(metric),
        last_hour=queries.last_60_minutes(metric),
        blocked_today=blocked,
    )


def _metric_summary(
    metric: UsageMetric,
    usage: MetricUsage,
    *,
    config: UsageConfig,
    enforcement: Mapping[str, object],
    now: datetime,
) -> dict[str, JsonValue]:
    section = _metric_section(config, metric)
    cap = section.daily_cap
    quota = section.monthly_quota
    percents = section.alert_thresholds_percent
    thresholds: list[JsonValue] = [_json_value(item) for item in percents]
    return {
        "metric": metric,
        "policy": str(section.over_limit_policy),
        "today": _today_window(usage.used_day, cap),
        "month": _month_window(usage.used_month, quota, now=now),
        "enforcement": _metric_enforcement(enforcement, metric),
        "thresholds_percent": thresholds,
        "next_threshold": _next_threshold(usage, cap=cap, quota=quota, thresholds=percents),
        "blocked_today": usage.blocked_today,
        "last_hour": usage.last_hour,
    }


def _today_window(used: int, cap: int | None) -> dict[str, JsonValue]:
    return {
        "used": used,
        "cap": cap,
        "remaining": None if cap is None else cap - used,
        "percent": _ratio_percent(used, cap),
    }


def _month_window(used: int, quota: int | None, *, now: datetime) -> dict[str, JsonValue]:
    local = now.astimezone(_local_tz())
    last_day = calendar.monthrange(local.year, local.month)[1]
    return {
        "used": used,
        "quota": quota,
        "remaining": None if quota is None else quota - used,
        "percent": _ratio_percent(used, quota),
        "period_start": f"{local.year:04d}-{local.month:02d}-01",
        "period_end": f"{local.year:04d}-{local.month:02d}-{last_day:02d}",
        "projected": _month_projected(used, local=local, quota=quota, last_day=last_day),
    }


def _month_projected(used: int, *, local: datetime, quota: int | None, last_day: int) -> int | None:
    if quota is None:
        return None
    return round(used * last_day / local.day)


def _next_threshold(
    usage: MetricUsage,
    *,
    cap: int | None,
    quota: int | None,
    thresholds: Sequence[int],
) -> dict[str, JsonValue] | None:
    candidates: list[tuple[int, str, int]] = []
    for percent in thresholds:
        _offer_threshold(candidates, used=usage.used_day, limit=cap, percent=percent, scope="day")
        _offer_threshold(
            candidates,
            used=usage.used_month,
            limit=quota,
            percent=percent,
            scope="month",
        )
    if not candidates:
        return None
    remaining, scope, percent = min(candidates)
    return {"scope": scope, "percent": percent, "remaining": remaining}


def _offer_threshold(
    candidates: list[tuple[int, str, int]],
    *,
    used: int,
    limit: int | None,
    percent: int,
    scope: str,
) -> None:
    if limit is None:
        return
    absolute = limit * percent // 100
    if used < absolute:
        candidates.append((absolute - used, scope, percent))


def _ratio_percent(used: int, limit: int | None) -> float | None:
    if limit is None:
        return None
    if limit == 0:
        raise ValueError(ZERO_LIMIT_MESSAGE)
    return round(used * 100 / limit, 2)


def _api_breakdown_today(day_start: datetime, day_end: datetime) -> dict[str, JsonValue]:
    billed = queries.used_today("api")
    api_total = queries.used_in_range("api", day_start, day_end, billed_only=False)
    unbilled = api_total - billed
    if unbilled < 0:
        raise ValueError(NEGATIVE_UNBILLED_MESSAGE)
    internal = queries.used_today("internal")
    return {
        "total": billed + unbilled + internal,
        "billed": billed,
        "unbilled": unbilled,
        "internal": internal,
    }


def _alerts_summary(config: UsageConfig, *, now: datetime) -> dict[str, JsonValue]:
    day_start, day_end = _local_day_bounds(now)
    ready, problem, recipient_count = alerts.sender_status()
    return {
        "sent_today": _alert_count(day_start, day_end, status="sent"),
        "suppressed_today": _alert_count(day_start, day_end, status="suppressed"),
        "daily_cap": int(config.alerts.daily_cap),
        "sender_ready": ready,
        "sender_problem": problem,
        "recipient_count": recipient_count,
    }


def _alert_count(day_start: datetime, day_end: datetime, *, status: str) -> int:
    return UsageAlertEvent.objects.filter(
        created_at__gte=day_start,
        created_at__lt=day_end,
        status=status,
    ).count()


def _authentik_payload(runtime: UsageRuntimeState | None, *, now: datetime) -> dict[str, JsonValue]:
    if runtime is None:
        return {"pulled_at": None, "stale": True, "error": None}
    pulled_at = runtime.authentik_pulled_at
    stale = pulled_at is None or now - pulled_at > AUTHENTIK_STALE_AFTER
    error = runtime.authentik_error or None
    return {"pulled_at": datetime_value(pulled_at), "stale": stale, "error": error}


def _series_point_payload(point: UsageSeriesPoint) -> dict[str, JsonValue]:
    start = point.start
    if start.tzinfo is None:
        message = "时间序列点 start 缺少时区。"
        raise ValueError(message)
    return {
        "start": datetime_value(start.astimezone(_local_tz())),
        "api_billed": point.api_billed,
        "api_unbilled": point.api_unbilled,
        "internal": point.internal,
        "webhook": point.webhook,
        "stream": point.stream,
        "blocked": point.blocked,
    }


def _series_totals(points: Sequence[dict[str, JsonValue]]) -> dict[str, JsonValue]:
    totals = {
        "api_billed": 0,
        "api_unbilled": 0,
        "internal": 0,
        "webhook": 0,
        "stream": 0,
        "blocked": 0,
    }
    for point in points:
        for key in totals:
            totals[key] += _json_int(point[key])
    return cast("dict[str, JsonValue]", totals)


def _category_payload(item: UsageCategoryTotal) -> dict[str, JsonValue]:
    registered = usage_category(item.category)
    return {
        "metric": item.metric,
        "category": item.category,
        # 控制台 API 没有请求语言协商, 同时返回中英标签供前端 `label ?? label_zh` 读取。
        "label_zh": registered.label_zh,
        "label_en": registered.label_en,
        "source": item.source,
        "billed": item.billed,
        "priority": item.priority,
        "count": item.count,
        "blocked": item.blocked,
    }


def _metric_section(config: UsageConfig, metric: UsageMetric) -> MetricQuotaConfig:
    match metric:
        case "api":
            return config.api
        case "webhook":
            return config.webhook
        case "stream":
            return config.stream
        case "internal":
            raise ValueError(INTERNAL_HAS_NO_QUOTA_MESSAGE)


def _enforcement_map(runtime: UsageRuntimeState | None) -> dict[str, object]:
    if runtime is None:
        return {}
    nested: object = runtime.enforcement.get("metrics")
    if nested is None:
        return {}
    if not isinstance(nested, dict):
        raise TypeError(ENFORCEMENT_OBJECT_MESSAGE)
    return cast("dict[str, object]", nested)


def _metric_enforcement(enforcement: Mapping[str, object], metric: str) -> dict[str, JsonValue]:
    raw = enforcement.get(metric)
    if raw is None:
        return {"state": "normal", "reason": None, "since": None}
    if not isinstance(raw, dict):
        raise TypeError(ENFORCEMENT_METRIC_OBJECT_MESSAGE)
    item = cast("dict[str, object]", raw)
    state = item.get("state", "normal")
    if not isinstance(state, str) or state not in ENFORCEMENT_STATES:
        raise TypeError(ENFORCEMENT_STATE_MESSAGE)
    return {"state": state, "reason": _enforcement_reason(item), "since": _enforcement_since(item)}


def _enforcement_reason(item: Mapping[str, object]) -> str | None:
    reason = item.get("reason")
    if reason is None:
        return None
    if not isinstance(reason, str) or reason not in LIMIT_REASONS:
        raise TypeError(ENFORCEMENT_REASON_MESSAGE)
    return reason


def _enforcement_since(item: Mapping[str, object]) -> str | None:
    raw = item.get("since")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return datetime_value(raw)
    if isinstance(raw, str):
        return raw
    raise TypeError(ENFORCEMENT_SINCE_MESSAGE)


def _runtime_state() -> UsageRuntimeState | None:
    return UsageRuntimeState.objects.filter(pk=USAGE_SINGLETON_ID).first()


def _local_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    local = now.astimezone(_local_tz())
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _timezone_name() -> str:
    return timezone.get_current_timezone_name()


def _local_tz() -> ZoneInfo:
    return ZoneInfo(_timezone_name())


def _json_value(value: JsonValue) -> JsonValue:
    return value


def _json_object_list(items: Sequence[dict[str, JsonValue]]) -> list[JsonValue]:
    return [_json_value(item) for item in items]


def _json_int(value: JsonValue) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        message = "时间序列汇总字段必须是整数。"
        raise TypeError(message)
    return value


def _query_error(message: str, *, field: str, value: str) -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        {"field": field, "value": value},
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def _bad_range(message: str, *, field: str, value: str | None) -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        {"field": field, "value": "" if value is None else value},
        status=HTTPStatus.BAD_REQUEST,
    )
