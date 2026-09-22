from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from easyauth.usage.models import UsageBucket
from easyauth.usage.queries import (
    baseline_same_hour_avg,
    breakdown,
    current_hour,
    day_period_key,
    month_period_key,
    timeseries,
    used_in_range,
    used_this_month,
    used_today,
)
from easyauth.usage.recorder import record
from easyauth.usage.registry import (
    SOURCE_AUTHENTIK,
    SOURCE_EASYAUTH,
)
from easyauth.usage.registry import (
    category as usage_category,
)

pytestmark = pytest.mark.django_db

SHANGHAI = "Asia/Shanghai"


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _freeze(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    monkeypatch.setattr("django.utils.timezone.now", lambda: moment)


def _write_bucket(
    hour_start: datetime,
    category_key: str,
    count: int,
    *,
    source: str = SOURCE_EASYAUTH,
    blocked: int = 0,
) -> None:
    spec = usage_category(category_key)
    _ = UsageBucket.objects.create(
        hour_start=hour_start,
        source=source,
        category=category_key,
        metric=spec.metric,
        billed=spec.billed,
        count=count,
        blocked_count=blocked,
    )


@override_settings(TIME_ZONE=SHANGHAI)
def test_merge_without_double_count(monkeypatch: pytest.MonkeyPatch) -> None:
    now = _utc(2026, 9, 21, 6)
    _freeze(monkeypatch, now)
    hour = _utc(2026, 9, 21, 6)
    _write_bucket(hour, "notify_send", 4)
    record("notify_send")
    start, end = hour, hour + timedelta(hours=1)
    assert used_in_range("api", start, end, billed_only=True) == 4
    record("notify_send")
    record("notify_send")
    record("notify_send")
    record("notify_send")
    record("notify_send")
    assert used_in_range("api", start, end, billed_only=True) == 6


@override_settings(TIME_ZONE=SHANGHAI)
def test_today_and_month_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    # 2026-10-01 00:30 +08 = 2026-09-30 16:30 UTC
    _freeze(monkeypatch, _utc(2026, 9, 30, 16, 30))
    _write_bucket(_utc(2026, 9, 30, 15), "notify_send", 10)
    _write_bucket(_utc(2026, 9, 30, 16), "notify_send", 3)
    _write_bucket(_utc(2026, 9, 30, 16), "token", 8)
    assert used_today("api") == 3
    assert used_this_month("api") == 3
    now = timezone.now()
    assert day_period_key(now) == "2026-10-01"
    assert month_period_key(now) == "2026-10"


@override_settings(TIME_ZONE=SHANGHAI)
def test_current_hour_excludes_previous_clock_hour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze(monkeypatch, _utc(2026, 9, 21, 6, 30))
    _write_bucket(_utc(2026, 9, 21, 5), "notify_send", 5)
    _write_bucket(_utc(2026, 9, 21, 6), "notify_send", 7)
    _write_bucket(_utc(2026, 9, 21, 4), "notify_send", 100)
    assert current_hour("api") == 7


@override_settings(TIME_ZONE=SHANGHAI)
def test_baseline_same_hour_average(monkeypatch: pytest.MonkeyPatch) -> None:
    # 本地 14:00+08 = 06:00 UTC; 不含当天。
    _freeze(monkeypatch, datetime(2026, 9, 21, 6, 10, tzinfo=UTC))
    for day in range(14, 21):
        _write_bucket(_utc(2026, 9, day, 6), "notify_send", 10)
    _write_bucket(_utc(2026, 9, 21, 6), "notify_send", 999)
    assert baseline_same_hour_avg("api", days=7) == 10.0


@override_settings(TIME_ZONE=SHANGHAI)
def test_timeseries_hour_zero_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, _utc(2026, 9, 21, 8))
    _write_bucket(_utc(2026, 9, 21, 7), "notify_send", 4, blocked=1)
    start = _utc(2026, 9, 21, 6)
    end = _utc(2026, 9, 21, 9)
    points = timeseries(start, end, "hour")
    assert [item.start for item in points] == [
        timezone.localtime(start),
        timezone.localtime(_utc(2026, 9, 21, 7)),
        timezone.localtime(_utc(2026, 9, 21, 8)),
    ]
    assert points[0].api_billed == 0
    assert points[1].api_billed == 4
    assert points[1].blocked == 1
    assert points[2].api_billed == 0


@override_settings(TIME_ZONE=SHANGHAI)
def test_timeseries_day_zero_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, _utc(2026, 9, 22, 4))
    # 2026-09-21 00:00+08 = 2026-09-20 16:00 UTC
    _write_bucket(_utc(2026, 9, 20, 16), "notify_send", 2)
    start = datetime(2026, 9, 21, tzinfo=timezone.get_current_timezone())
    end = datetime(2026, 9, 24, tzinfo=timezone.get_current_timezone())
    points = timeseries(start, end, "day")
    assert len(points) == 3
    assert points[0].api_billed == 2
    assert points[1].api_billed == 0
    assert points[2].api_billed == 0
    assert points[0].start.date().isoformat() == "2026-09-21"
    assert points[1].start.date().isoformat() == "2026-09-22"
    assert points[2].start.date().isoformat() == "2026-09-23"


@override_settings(TIME_ZONE=SHANGHAI)
def test_breakdown_by_category_and_source(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, _utc(2026, 9, 21, 6))
    hour = _utc(2026, 9, 21, 6)
    _write_bucket(hour, "notify_send", 4, blocked=1)
    _write_bucket(hour, "ak_directory_full", 9, source=SOURCE_AUTHENTIK)
    record("token")
    rows = breakdown(hour, hour + timedelta(hours=1))
    by_key = {(item.source, item.category): item for item in rows}
    assert by_key[(SOURCE_EASYAUTH, "notify_send")].count == 4
    assert by_key[(SOURCE_EASYAUTH, "notify_send")].blocked == 1
    assert by_key[(SOURCE_EASYAUTH, "notify_send")].priority == "p1"
    assert by_key[(SOURCE_AUTHENTIK, "ak_directory_full")].count == 9
    assert by_key[(SOURCE_EASYAUTH, "token")].count == 1
    assert by_key[(SOURCE_EASYAUTH, "token")].billed is False
