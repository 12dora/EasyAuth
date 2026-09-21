from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from easyauth.tasks.usage_evaluate import (
    USAGE_EVALUATE_TASK_NAME,
    evaluate_usage,
    evaluate_usage_task,
)
from easyauth.usage.alerts import ALERT_KIND_STREAM_PAUSED, ALERT_KIND_THRESHOLD, STATUS_SENT
from easyauth.usage.config import DEFAULT_USAGE_DOCUMENT, UsageConfig, save
from easyauth.usage.models import UsageAlertEvent, UsageRuntimeState

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 9, 21, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


def _patch_queries(monkeypatch: pytest.MonkeyPatch, *, day: dict[str, int]) -> None:
    monkeypatch.setattr(
        "easyauth.usage.enforcement.used_today",
        lambda metric: day.get(metric, 0),
    )
    monkeypatch.setattr("easyauth.usage.enforcement.used_this_month", lambda _metric: 0)
    monkeypatch.setattr("easyauth.usage.alerts.used_today", lambda metric: day.get(metric, 0))
    monkeypatch.setattr("easyauth.usage.alerts.used_this_month", lambda _metric: 0)
    monkeypatch.setattr("easyauth.usage.alerts.last_60_minutes", lambda _metric: 0)
    monkeypatch.setattr(
        "easyauth.usage.alerts.baseline_same_hour_avg",
        lambda _metric, **_kwargs: 0.0,
    )
    monkeypatch.setattr("easyauth.usage.enforcement.day_period_key", lambda _now: "2026-09-21")
    monkeypatch.setattr("easyauth.usage.enforcement.month_period_key", lambda _now: "2026-09")
    monkeypatch.setattr("easyauth.usage.alerts.day_period_key", lambda _now: "2026-09-21")
    monkeypatch.setattr("easyauth.usage.alerts.month_period_key", lambda _now: "2026-09")


def _silence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("easyauth.usage.alerts.send_merged_alert", lambda *_args: None)


def test_task_name() -> None:
    assert evaluate_usage_task.name == USAGE_EVALUATE_TASK_NAME
    assert USAGE_EVALUATE_TASK_NAME == "easyauth.usage.evaluate"


def test_evaluate_usage_computes_state_and_emits_alerts(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence(monkeypatch)
    _patch_queries(monkeypatch, day={"api": 2500})
    state = evaluate_usage(NOW)
    assert state.metrics["api"].state == "normal"
    row = UsageRuntimeState.objects.get(pk=1)
    assert row.evaluated_at == NOW
    sent = UsageAlertEvent.objects.filter(kind=ALERT_KIND_THRESHOLD, status=STATUS_SENT)
    assert sent.count() == 1


def test_evaluate_usage_records_stream_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    _silence(monkeypatch)
    document = cast("dict[str, object]", deepcopy(DEFAULT_USAGE_DOCUMENT))
    stream = document["stream"]
    assert isinstance(stream, dict)
    stream["daily_cap"] = 10
    stream["over_limit_policy"] = "pause_stream"
    save(UsageConfig.model_validate(document), updated_by="t")
    _patch_queries(monkeypatch, day={"stream": 10})
    state = evaluate_usage(NOW)
    assert state.stream_paused is True
    assert state.stream_transition == "paused"
    row = UsageRuntimeState.objects.get(pk=1)
    assert row.stream_paused is True
    assert UsageAlertEvent.objects.filter(kind=ALERT_KIND_STREAM_PAUSED).exists()
