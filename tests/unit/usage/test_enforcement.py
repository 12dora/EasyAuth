from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache
from django.utils import timezone

from easyauth.usage.config import DEFAULT_USAGE_DOCUMENT, UsageConfig, save
from easyauth.usage.enforcement import (
    ENFORCEMENT_CACHE_KEY,
    EnforcementState,
    MetricEnforcement,
    StreamNotPausedError,
    authentik_policy,
    decide,
    evaluate,
    resume_stream,
    stream_should_run,
)
from easyauth.usage.models import UsageRuntimeState
from easyauth.usage.registry import UsageCategory, UsagePriority

NOW = datetime(2026, 9, 21, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


def _document() -> dict[str, object]:
    return cast("dict[str, object]", deepcopy(DEFAULT_USAGE_DOCUMENT))


def _section(document: dict[str, object], name: str) -> dict[str, object]:
    section = document[name]
    assert isinstance(section, dict)
    return section


def _config(
    *,
    api: dict[str, object] | None = None,
    stream: dict[str, object] | None = None,
) -> UsageConfig:
    document = _document()
    if api is not None:
        _section(document, "api").update(api)
    if stream is not None:
        _section(document, "stream").update(stream)
    return UsageConfig.model_validate(document)


def _patch_usage(
    monkeypatch: pytest.MonkeyPatch,
    *,
    day: dict[str, int] | None = None,
    month: dict[str, int] | None = None,
) -> None:
    day_map = day or {}
    month_map = month or {}
    monkeypatch.setattr(
        "easyauth.usage.enforcement.used_today",
        lambda metric: day_map.get(metric, 0),
    )
    monkeypatch.setattr(
        "easyauth.usage.enforcement.used_this_month",
        lambda metric: month_map.get(metric, 0),
    )
    monkeypatch.setattr("easyauth.usage.enforcement.day_period_key", lambda _now: "2026-09-21")
    monkeypatch.setattr("easyauth.usage.enforcement.month_period_key", lambda _now: "2026-09")


def _category(
    *,
    billed: bool = True,
    priority: UsagePriority | None = "p1",
) -> UsageCategory:
    return UsageCategory(
        key="notify_send",
        metric="api",
        billed=billed,
        priority=priority,
        label_zh="工作通知发送",
        label_en="notify send",
    )


def _put_state(
    name: str,
    *,
    reason: str | None = "daily_cap",
    daily_cap: int | None = 5000,
    policy: str = "degrade",
    throttle: dict[str, int] | None = None,
) -> None:
    now = timezone.now()
    limits = {"p1": 200, "p2": 20} if throttle is None else throttle
    payload = {
        "metrics": {
            "api": {
                "metric": "api",
                "state": name,
                "reason": None if name == "normal" else reason,
                "since": now.isoformat(),
            },
            "webhook": {
                "metric": "webhook",
                "state": "normal",
                "reason": None,
                "since": None,
            },
            "stream": {
                "metric": "stream",
                "state": "stream_paused" if name == "stream_paused" else "normal",
                "reason": None,
                "since": None,
            },
        },
        "evaluated_at": now.isoformat(),
        "stream_paused": name == "stream_paused",
        "stream_paused_at": now.isoformat() if name == "stream_paused" else None,
        "stream_paused_period": "2026-09-21" if name == "stream_paused" else "",
        "stream_manual_resume_period": "",
        "api_daily_cap": daily_cap,
        "api_over_limit_policy": policy,
        "throttle_per_hour": limits,
    }
    cache.set(ENFORCEMENT_CACHE_KEY, payload, 60)


def _state_for(name: str) -> EnforcementState:
    now = timezone.now()
    return EnforcementState(
        metrics={
            "api": MetricEnforcement("api", name, "daily_cap" if name != "normal" else None, now),
            "webhook": MetricEnforcement("webhook", "normal", None, None),
            "stream": MetricEnforcement("stream", "normal", None, None),
        },
        evaluated_at=now,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("policy", "used_day", "used_month", "expected"),
    [
        ("alert_only", 0, 0, "normal"),
        ("alert_only", 5000, 0, "normal"),
        ("alert_only", 0, 500000, "normal"),
        ("degrade", 0, 0, "normal"),
        ("degrade", 5000, 0, "degraded_p2"),
        ("degrade", 0, 500000, "degraded_p2"),
        ("degrade", 0, 600000, "degraded_p1"),
        ("degrade", 5000, 600000, "degraded_p1"),
        ("throttle", 0, 0, "normal"),
        ("throttle", 5000, 0, "throttled"),
        ("block_all", 0, 0, "normal"),
        ("block_all", 5000, 0, "blocked"),
        ("block_all", 0, 500000, "blocked"),
    ],
)
def test_api_policy_state_transitions(
    monkeypatch: pytest.MonkeyPatch,
    policy: str,
    used_day: int,
    used_month: int,
    expected: str,
) -> None:
    save(_config(api={"over_limit_policy": policy}), updated_by="tester")
    _patch_usage(monkeypatch, day={"api": used_day}, month={"api": used_month})
    state = evaluate(NOW)
    assert state.metrics["api"].state == expected
    if expected == "degraded_p1" or (expected == "degraded_p2" and used_month >= 500000):
        assert state.metrics["api"].reason == "monthly_quota"
    elif expected != "normal":
        assert state.metrics["api"].reason in {"daily_cap", "monthly_quota"}


@pytest.mark.django_db
def test_evaluate_writes_decide_policy_into_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    save(
        _config(api={"daily_cap": 1234, "throttle_per_hour": {"p1": 9, "p2": 4}}),
        updated_by="tester",
    )
    _patch_usage(monkeypatch)
    state = evaluate(NOW)
    payload = cache.get(ENFORCEMENT_CACHE_KEY)
    assert isinstance(payload, dict)
    assert payload["api_daily_cap"] == 1234
    assert payload["api_over_limit_policy"] == "degrade"
    assert payload["throttle_per_hour"] == {"p1": 9, "p2": 4}
    evaluated = payload["evaluated_at"]
    assert isinstance(evaluated, str)
    assert datetime.fromisoformat(evaluated) == state.evaluated_at


@pytest.mark.django_db
def test_webhook_stays_normal_when_over_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    save(_config(), updated_by="tester")
    _patch_usage(monkeypatch, day={"webhook": 999999}, month={"webhook": 999999})
    state = evaluate(NOW)
    assert state.metrics["webhook"].state == "normal"


@pytest.mark.django_db
def test_stream_alert_only_does_not_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    save(_config(stream={"daily_cap": 10, "over_limit_policy": "alert_only"}), updated_by="t")
    _patch_usage(monkeypatch, day={"stream": 10})
    state = evaluate(NOW)
    assert state.metrics["stream"].state == "normal"
    assert state.stream_paused is False
    assert stream_should_run() is True


@pytest.mark.django_db
def test_stream_pause_auto_resume_and_manual_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    save(_config(stream={"daily_cap": 10, "over_limit_policy": "pause_stream"}), updated_by="t")
    _patch_usage(monkeypatch, day={"stream": 10})
    paused = evaluate(NOW)
    assert paused.stream_paused is True
    assert paused.stream_paused_period == "2026-09-21"
    assert paused.stream_transition == "paused"
    assert stream_should_run() is False
    resume_stream("admin-1")
    assert stream_should_run() is True
    again = evaluate(NOW)
    assert again.stream_paused is False
    assert again.stream_manual_resume_period == "2026-09-21"


@pytest.mark.django_db
def test_stream_not_re_paused_after_manual_resume_same_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save(_config(stream={"daily_cap": 10, "over_limit_policy": "pause_stream"}), updated_by="t")
    _patch_usage(monkeypatch, day={"stream": 10})
    _ = evaluate(NOW)
    resume_stream("admin-1")
    state = evaluate(NOW)
    assert state.stream_paused is False
    assert state.metrics["stream"].state == "normal"


@pytest.mark.django_db
def test_stream_auto_resumes_on_period_rollover_when_under_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save(_config(stream={"daily_cap": 10, "over_limit_policy": "pause_stream"}), updated_by="t")
    _patch_usage(monkeypatch, day={"stream": 10})
    _ = evaluate(NOW)
    _patch_usage(monkeypatch, day={"stream": 1})
    monkeypatch.setattr("easyauth.usage.enforcement.day_period_key", lambda _now: "2026-09-22")
    state = evaluate(NOW)
    assert state.stream_paused is False
    assert state.stream_transition == "resumed"


@pytest.mark.django_db
def test_resume_stream_when_not_paused_raises() -> None:
    with pytest.raises(StreamNotPausedError):
        resume_stream("admin-1")


def test_unbilled_always_allowed() -> None:
    _put_state("blocked")
    assert decide(_category(billed=False, priority="p2")) is True


@pytest.mark.parametrize(
    ("state_name", "p0", "p1", "p2"),
    [
        ("normal", True, True, True),
        ("degraded_p2", True, True, False),
        ("degraded_p1", True, False, False),
        ("blocked", False, False, False),
        ("stream_paused", True, True, True),
    ],
)
def test_decide_priorities_per_state(
    state_name: str,
    *,
    p0: bool,
    p1: bool,
    p2: bool,
) -> None:
    _put_state(state_name)
    assert decide(_category(priority="p0")) is p0
    assert decide(_category(priority="p1")) is p1
    assert decide(_category(priority="p2")) is p2


def test_decide_hot_path_does_not_touch_database() -> None:
    billed_p2 = _category(priority="p2")
    cache.delete(ENFORCEMENT_CACHE_KEY)
    assert decide(billed_p2) is True
    _put_state("degraded_p2")
    assert decide(billed_p2) is False
    assert decide(_category(priority="p1")) is True


def test_throttle_counters() -> None:
    _put_state("throttled", policy="throttle", throttle={"p1": 2, "p2": 1})
    assert decide(_category(priority="p0")) is True
    assert decide(_category(priority="p1")) is True
    assert decide(_category(priority="p1")) is True
    assert decide(_category(priority="p1")) is False
    assert decide(_category(priority="p2")) is True
    assert decide(_category(priority="p2")) is False


def test_realtime_daily_cap_uses_cached_day_counters() -> None:
    _put_state("normal", daily_cap=5000, policy="degrade")
    stamp = timezone.localtime(timezone.now()).strftime("%Y%m%d")
    cache.set(f"usage:day:{stamp}:api_billed", 4000, 60)
    cache.set(f"usage:day:{stamp}:api_billed_authentik", 1000, 60)
    assert decide(_category(priority="p2")) is False
    assert decide(_category(priority="p1")) is True


def test_realtime_daily_cap_missing_cache_allows() -> None:
    _put_state("normal")
    assert decide(_category(priority="p2")) is True


@pytest.mark.django_db
def test_since_is_preserved_while_state_stays(monkeypatch: pytest.MonkeyPatch) -> None:
    save(_config(api={"over_limit_policy": "degrade"}), updated_by="t")
    _patch_usage(monkeypatch, day={"api": 5000})
    first = evaluate(NOW)
    since = first.metrics["api"].since
    second = evaluate(NOW)
    assert second.metrics["api"].state == "degraded_p2"
    assert second.metrics["api"].since == since


@pytest.mark.django_db
def test_authentik_policy_body_for_each_state() -> None:
    normal = authentik_policy(_state_for("normal"))
    assert normal["blocked_priorities"] == []
    assert normal["throttle_per_hour"] == {"p1": None, "p2": None}
    assert normal["block_p0_billed"] is False
    assert str(normal["expires_at"]).endswith("Z")
    assert authentik_policy(_state_for("degraded_p2"))["blocked_priorities"] == ["p2"]
    assert authentik_policy(_state_for("degraded_p1"))["blocked_priorities"] == ["p1", "p2"]
    blocked = authentik_policy(_state_for("blocked"))
    assert blocked["block_p0_billed"] is True
    assert blocked["blocked_priorities"] == ["p1", "p2"]
    save(
        _config(api={"over_limit_policy": "throttle", "throttle_per_hour": {"p1": 9, "p2": 3}}),
        updated_by="t",
    )
    throttled = authentik_policy(_state_for("throttled"))
    assert throttled["throttle_per_hour"] == {"p1": 9, "p2": 3}


@pytest.mark.django_db
def test_stream_should_run_falls_back_to_db() -> None:
    cache.delete(ENFORCEMENT_CACHE_KEY)
    _ = UsageRuntimeState.objects.create(
        pk=1,
        enforcement={},
        evaluated_at=timezone.now(),
        stream_paused=True,
        stream_paused_period="2026-09-21",
        stream_manual_resume_period="",
        authentik_error="",
    )
    assert stream_should_run() is False
    cache.delete(ENFORCEMENT_CACHE_KEY)
    UsageRuntimeState.objects.filter(pk=1).update(stream_paused=False)
    assert stream_should_run() is True
