from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache

from easyauth.tasks.usage_evaluate import (
    EVALUATE_RUN_LOCK_KEY,
    EVALUATE_RUN_LOCK_TTL_SECONDS,
    EVALUATE_SKIPPED_RESULT,
    USAGE_EVALUATE_TASK_NAME,
    evaluate_usage,
    evaluate_usage_task,
)
from easyauth.usage.alert_delivery import MergedAlertDelivery
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
    monkeypatch.setattr("easyauth.usage.alerts.current_hour", lambda _metric: 0)
    monkeypatch.setattr(
        "easyauth.usage.alerts.baseline_same_hour_avg",
        lambda _metric, **_kwargs: 0.0,
    )
    monkeypatch.setattr("easyauth.usage.enforcement.day_period_key", lambda _now: "2026-09-21")
    monkeypatch.setattr("easyauth.usage.enforcement.month_period_key", lambda _now: "2026-09")
    monkeypatch.setattr("easyauth.usage.alerts.day_period_key", lambda _now: "2026-09-21")
    monkeypatch.setattr("easyauth.usage.alerts.month_period_key", lambda _now: "2026-09")


def _silence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "easyauth.usage.alerts.send_merged_alert",
        lambda *_args: MergedAlertDelivery(failure_reason=None, handed_off=True),
    )


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


def _normal_state(_now: datetime | None = None) -> SimpleNamespace:
    _ = _now
    return SimpleNamespace(metrics={"api": SimpleNamespace(state="normal")})


def test_evaluate_task_lock_wraps_one_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    held = {"value": False}

    def fake(_now: datetime | None = None) -> SimpleNamespace:
        held["value"] = cache.get(EVALUATE_RUN_LOCK_KEY) is not None
        return _normal_state()

    monkeypatch.setattr("easyauth.tasks.usage_evaluate.evaluate_usage", fake)
    assert evaluate_usage_task() == "normal"
    assert held["value"] is True
    assert cache.get(EVALUATE_RUN_LOCK_KEY) is None


def test_evaluate_task_skips_when_lock_held(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = {"n": 0}

    def fake(_now: datetime | None = None) -> SimpleNamespace:
        calls["n"] += 1
        return _normal_state()

    monkeypatch.setattr("easyauth.tasks.usage_evaluate.evaluate_usage", fake)
    assert cache.add(EVALUATE_RUN_LOCK_KEY, "1", timeout=EVALUATE_RUN_LOCK_TTL_SECONDS) is True
    try:
        with caplog.at_level("DEBUG", logger="easyauth.tasks.usage_evaluate"):
            assert evaluate_usage_task() == EVALUATE_SKIPPED_RESULT
        assert calls["n"] == 0
        assert "跳过本轮" in caplog.text
    finally:
        _ = cache.delete(EVALUATE_RUN_LOCK_KEY)


def test_evaluate_task_releases_lock_when_evaluate_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_now: datetime | None = None) -> SimpleNamespace:
        message = "evaluate failed"
        raise RuntimeError(message)

    monkeypatch.setattr("easyauth.tasks.usage_evaluate.evaluate_usage", boom)
    with pytest.raises(RuntimeError, match="evaluate failed"):
        _ = evaluate_usage_task()
    assert cache.get(EVALUATE_RUN_LOCK_KEY) is None


def test_evaluate_task_keeps_lock_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter((0.0, 1_000.0))
    deleted: list[str] = []
    real_delete = cache.delete
    monkeypatch.setattr("easyauth.tasks.usage_evaluate.monotonic", lambda: next(ticks))
    monkeypatch.setattr(
        "easyauth.tasks.usage_evaluate.cache.delete",
        lambda key: deleted.append(str(key)),
    )
    monkeypatch.setattr("easyauth.tasks.usage_evaluate.evaluate_usage", _normal_state)
    try:
        assert evaluate_usage_task() == "normal"
        assert deleted == []
    finally:
        real_delete(EVALUATE_RUN_LOCK_KEY)
