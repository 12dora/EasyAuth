from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, Literal

from django.utils import timezone

from easyauth.usage.models import UsageBucket
from easyauth.usage.recorder import cached_hour_counts, open_hour_starts, truncate_hour_utc
from easyauth.usage.registry import SOURCE_EASYAUTH, category

if TYPE_CHECKING:
    from datetime import date

    from easyauth.usage.registry import UsageMetric, UsagePriority, UsageSource

type TimeseriesGranularity = Literal["hour", "day"]

MONTHS_IN_YEAR: Final = 12


@dataclass(frozen=True, slots=True)
class UsageSeriesPoint:
    start: datetime
    api_billed: int
    api_unbilled: int
    internal: int
    webhook: int
    stream: int
    blocked: int


@dataclass(frozen=True, slots=True)
class UsageCategoryTotal:
    metric: UsageMetric
    category: str
    source: UsageSource
    billed: bool
    priority: UsagePriority | None
    count: int
    blocked: int


@dataclass(frozen=True, slots=True)
class _MergedBucket:
    hour_start: datetime
    source: UsageSource
    category_key: str
    count: int
    blocked: int


def used_in_range(
    metric: UsageMetric,
    start: datetime,
    end: datetime,
    *,
    billed_only: bool,
) -> int:
    total = 0
    for item in _merged_rows(start, end).values():
        spec = category(item.category_key)
        if spec.metric != metric:
            continue
        if billed_only and not spec.billed:
            continue
        total += item.count
    return total


def used_today(metric: UsageMetric) -> int:
    start, end = _local_day_bounds(timezone.now())
    return used_in_range(metric, start, end, billed_only=metric == "api")


def used_this_month(metric: UsageMetric) -> int:
    start, end = _local_month_bounds(timezone.now())
    return used_in_range(metric, start, end, billed_only=metric == "api")


def current_hour(metric: UsageMetric) -> int:
    now_local = timezone.localtime(timezone.now())
    hour_start = now_local.replace(minute=0, second=0, microsecond=0)
    return used_in_range(
        metric,
        hour_start,
        hour_start + timedelta(hours=1),
        billed_only=False,
    )


def baseline_same_hour_avg(metric: UsageMetric, *, days: int = 7) -> float:
    if days < 1:
        message = "baseline 天数必须为正整数。"
        raise ValueError(message)
    now_local = timezone.localtime(timezone.now())
    total = 0
    for offset in range(1, days + 1):
        day = now_local.date() - timedelta(days=offset)
        hour_start = now_local.replace(
            year=day.year,
            month=day.month,
            day=day.day,
            minute=0,
            second=0,
            microsecond=0,
        )
        total += used_in_range(
            metric,
            hour_start,
            hour_start + timedelta(hours=1),
            billed_only=False,
        )
    return total / days


def timeseries(
    start: datetime,
    end: datetime,
    granularity: TimeseriesGranularity,
) -> list[UsageSeriesPoint]:
    _require_range(start, end)
    resolved: str = granularity
    if resolved == "hour":
        return _timeseries_hour(start, end)
    return _timeseries_day(start, end)


def breakdown(start: datetime, end: datetime) -> list[UsageCategoryTotal]:
    _require_range(start, end)
    totals: dict[tuple[str, str, str], UsageCategoryTotal] = {}
    for item in _merged_rows(start, end).values():
        spec = category(item.category_key)
        key = (spec.metric, item.category_key, item.source)
        current = totals.get(key)
        if current is None:
            totals[key] = UsageCategoryTotal(
                metric=spec.metric,
                category=item.category_key,
                source=item.source,
                billed=spec.billed,
                priority=spec.priority,
                count=item.count,
                blocked=item.blocked,
            )
            continue
        totals[key] = UsageCategoryTotal(
            metric=current.metric,
            category=current.category,
            source=current.source,
            billed=current.billed,
            priority=current.priority,
            count=current.count + item.count,
            blocked=current.blocked + item.blocked,
        )
    return sorted(totals.values(), key=_breakdown_sort_key)


def day_period_key(now: datetime) -> str:
    return timezone.localtime(_require_aware(now, label="now")).date().isoformat()


def month_period_key(now: datetime) -> str:
    local = timezone.localtime(_require_aware(now, label="now"))
    return f"{local.year:04d}-{local.month:02d}"


def _timeseries_hour(start: datetime, end: datetime) -> list[UsageSeriesPoint]:
    cursor, last = _hour_window(start, end)
    grouped = _group_by_hour(_merged_rows(start, end))
    points: list[UsageSeriesPoint] = []
    while cursor < last:
        points.append(_point_from_buckets(timezone.localtime(cursor), grouped.get(cursor, ())))
        cursor += timedelta(hours=1)
    return points


def _timeseries_day(start: datetime, end: datetime) -> list[UsageSeriesPoint]:
    start_date, end_date = _day_window(start, end)
    grouped = _group_by_local_date(_merged_rows(start, end))
    points: list[UsageSeriesPoint] = []
    day = start_date
    while day < end_date:
        day_start, _day_end = _local_day_bounds_for_date(day)
        points.append(_point_from_buckets(day_start, grouped.get(day, ())))
        day += timedelta(days=1)
    return points


def _merged_rows(start: datetime, end: datetime) -> dict[tuple[datetime, str, str], _MergedBucket]:
    start_hour, end_utc = _query_hour_bounds(start, end)
    merged = _persisted_rows(start_hour, end_utc)
    _merge_open_hours(merged, start_hour=start_hour, end_utc=end_utc)
    return merged


def _persisted_rows(
    start_hour: datetime,
    end_utc: datetime,
) -> dict[tuple[datetime, str, str], _MergedBucket]:
    merged: dict[tuple[datetime, str, str], _MergedBucket] = {}
    buckets = UsageBucket.objects.filter(hour_start__gte=start_hour, hour_start__lt=end_utc)
    for bucket in buckets:
        hour_start = truncate_hour_utc(bucket.hour_start)
        source = _as_source(bucket.source)
        key = (hour_start, source, bucket.category)
        merged[key] = _MergedBucket(
            hour_start=hour_start,
            source=source,
            category_key=bucket.category,
            count=bucket.count,
            blocked=bucket.blocked_count,
        )
    return merged


def _merge_open_hours(
    merged: dict[tuple[datetime, str, str], _MergedBucket],
    *,
    start_hour: datetime,
    end_utc: datetime,
) -> None:
    for hour_start in open_hour_starts():
        if hour_start < start_hour or hour_start >= end_utc:
            continue
        for category_key, pair in cached_hour_counts(hour_start).items():
            key = (hour_start, SOURCE_EASYAUTH, category_key)
            existing = merged.get(key)
            count = pair[0] if existing is None else max(existing.count, pair[0])
            blocked = pair[1] if existing is None else max(existing.blocked, pair[1])
            merged[key] = _MergedBucket(
                hour_start=hour_start,
                source=SOURCE_EASYAUTH,
                category_key=category_key,
                count=count,
                blocked=blocked,
            )


def _group_by_hour(
    rows: dict[tuple[datetime, str, str], _MergedBucket],
) -> dict[datetime, tuple[_MergedBucket, ...]]:
    grouped: dict[datetime, list[_MergedBucket]] = {}
    for item in rows.values():
        grouped.setdefault(item.hour_start, []).append(item)
    return {hour: tuple(items) for hour, items in grouped.items()}


def _group_by_local_date(
    rows: dict[tuple[datetime, str, str], _MergedBucket],
) -> dict[date, tuple[_MergedBucket, ...]]:
    grouped: dict[date, list[_MergedBucket]] = {}
    for item in rows.values():
        local_day = timezone.localtime(item.hour_start).date()
        grouped.setdefault(local_day, []).append(item)
    return {day: tuple(items) for day, items in grouped.items()}


def _point_from_buckets(start: datetime, buckets: tuple[_MergedBucket, ...]) -> UsageSeriesPoint:
    api_billed = 0
    api_unbilled = 0
    internal = 0
    webhook = 0
    stream = 0
    blocked = 0
    for item in buckets:
        spec = category(item.category_key)
        blocked += item.blocked
        if spec.metric == "api" and spec.billed:
            api_billed += item.count
        elif spec.metric == "api":
            api_unbilled += item.count
        elif spec.metric == "internal":
            internal += item.count
        elif spec.metric == "webhook":
            webhook += item.count
        elif spec.metric == "stream":
            stream += item.count
        else:
            message = f"未知用量指标: {spec.metric}"
            raise ValueError(message)
    return UsageSeriesPoint(
        start=start,
        api_billed=api_billed,
        api_unbilled=api_unbilled,
        internal=internal,
        webhook=webhook,
        stream=stream,
        blocked=blocked,
    )


def _hour_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    cursor = truncate_hour_utc(start)
    end_utc = _require_aware(end, label="end").astimezone(UTC)
    last = truncate_hour_utc(end)
    if end_utc != last:
        last += timedelta(hours=1)
    return cursor, last


def _day_window(start: datetime, end: datetime) -> tuple[date, date]:
    start_date = timezone.localtime(_require_aware(start, label="start")).date()
    end_local = timezone.localtime(_require_aware(end, label="end"))
    end_date = end_local.date()
    if end_local.time() != datetime.min.time():
        end_date += timedelta(days=1)
    return start_date, end_date


def _query_hour_bounds(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    _require_range(start, end)
    return truncate_hour_utc(start), _require_aware(end, label="end").astimezone(UTC)


def _local_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    return _local_day_bounds_for_date(timezone.localtime(_require_aware(now, label="now")).date())


def _local_day_bounds_for_date(day: date) -> tuple[datetime, datetime]:
    local_now = timezone.localtime(timezone.now())
    start = local_now.replace(
        year=day.year,
        month=day.month,
        day=day.day,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return start, start + timedelta(days=1)


def _local_month_bounds(now: datetime) -> tuple[datetime, datetime]:
    local = timezone.localtime(_require_aware(now, label="now"))
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == MONTHS_IN_YEAR:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _as_source(value: str) -> UsageSource:
    if value == "easyauth":
        return "easyauth"
    if value == "authentik":
        return "authentik"
    message = f"非法用量来源: {value}"
    raise ValueError(message)


def _require_range(start: datetime, end: datetime) -> None:
    _ = _require_aware(start, label="start")
    _ = _require_aware(end, label="end")
    if end <= start:
        message = "用量查询结束时间必须晚于开始时间。"
        raise ValueError(message)


def _require_aware(moment: datetime, *, label: str) -> datetime:
    if timezone.is_naive(moment):
        message = f"{label} 必须是带时区的 datetime。"
        raise ValueError(message)
    return moment


def _breakdown_sort_key(item: UsageCategoryTotal) -> tuple[str, str, str]:
    return (item.metric, item.source, item.category)
