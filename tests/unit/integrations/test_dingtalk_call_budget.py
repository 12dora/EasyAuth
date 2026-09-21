from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING, cast

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from easyauth.config.settings.base import parse_positive_int_setting
from easyauth.integrations.dingtalk import call_budget as budget_module
from easyauth.integrations.dingtalk.call_budget import (
    DINGTALK_CALL_CATEGORIES,
    DingTalkCallBudgets,
    DingTalkCallUsage,
    budget_health_reason,
    budget_health_status,
    format_usage_summary,
    record_and_check,
    usage_today,
)
from easyauth.integrations.dingtalk.errors import (
    DingTalkApiUnavailableError,
    DingTalkCallBudgetExceededError,
)

if TYPE_CHECKING:
    from easyauth.integrations.dingtalk.call_budget import DingTalkCallCategory

HARD_BUDGET = 5
RECONCILE_BUDGET = 2


class _FailingCache:
    def incr(self, key: str, delta: int = 1) -> int:
        del key, delta
        raise ConnectionError

    def add(self, key: str, value: object, timeout: int | None = None) -> bool:
        del key, value, timeout
        raise ConnectionError

    def get(self, key: str, default: object = None) -> object:
        del key, default
        raise ConnectionError


def _usage(*, total: int, reconcile: int = 0) -> DingTalkCallUsage:
    counts: dict[DingTalkCallCategory, int] = dict.fromkeys(DINGTALK_CALL_CATEGORIES, 0)
    counts["notify_reconcile"] = reconcile
    return DingTalkCallUsage(
        day=date(2026, 9, 21),
        total=total,
        by_category=counts,
        budgets=DingTalkCallBudgets(total=5000, notify_reconcile=1000),
    )


@override_settings(
    EASYAUTH_DINGTALK_DAILY_CALL_BUDGET=HARD_BUDGET,
    EASYAUTH_DINGTALK_DAILY_RECONCILE_CALL_BUDGET=RECONCILE_BUDGET,
)
def test_counts_per_category_and_total() -> None:
    record_and_check("token")
    record_and_check("notify_send")
    record_and_check("token")

    usage = usage_today()
    assert usage.total == 3
    assert usage.by_category["token"] == 2
    assert usage.by_category["notify_send"] == 1
    assert usage.by_category["notify_reconcile"] == 0
    assert usage.budgets.total == HARD_BUDGET
    assert usage.budgets.notify_reconcile == RECONCILE_BUDGET


@override_settings(
    EASYAUTH_DINGTALK_DAILY_CALL_BUDGET=HARD_BUDGET,
    EASYAUTH_DINGTALK_DAILY_RECONCILE_CALL_BUDGET=RECONCILE_BUDGET,
)
def test_day_rollover_resets_counters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(budget_module.timezone, "localdate", lambda: date(2026, 9, 21))
    record_and_check("approval")
    record_and_check("approval")
    assert usage_today().total == 2
    assert usage_today().day == date(2026, 9, 21)

    monkeypatch.setattr(budget_module.timezone, "localdate", lambda: date(2026, 9, 22))
    assert usage_today().total == 0
    record_and_check("approval")
    usage = usage_today()
    assert usage.day == date(2026, 9, 22)
    assert usage.total == 1
    assert usage.by_category["approval"] == 1


@override_settings(
    EASYAUTH_DINGTALK_DAILY_CALL_BUDGET=HARD_BUDGET,
    EASYAUTH_DINGTALK_DAILY_RECONCILE_CALL_BUDGET=RECONCILE_BUDGET,
)
def test_reconcile_cap_trips_while_notify_send_still_allowed() -> None:
    record_and_check("notify_reconcile")
    record_and_check("notify_reconcile")
    with pytest.raises(DingTalkCallBudgetExceededError, match="notify_reconcile"):
        record_and_check("notify_reconcile")
    record_and_check("notify_send")
    usage = usage_today()
    assert usage.by_category["notify_reconcile"] == RECONCILE_BUDGET
    assert usage.by_category["notify_send"] == 1
    assert usage.total == 3


@override_settings(
    EASYAUTH_DINGTALK_DAILY_CALL_BUDGET=HARD_BUDGET,
    EASYAUTH_DINGTALK_DAILY_RECONCILE_CALL_BUDGET=1000,
)
def test_hard_cap_blocks_every_category_and_does_not_count_refusal() -> None:
    for _ in range(HARD_BUDGET):
        record_and_check("notify_send")
    with pytest.raises(DingTalkCallBudgetExceededError) as exc_info:
        record_and_check("token")
    assert isinstance(exc_info.value, DingTalkApiUnavailableError)
    with pytest.raises(DingTalkCallBudgetExceededError):
        record_and_check("notify_send")
    usage = usage_today()
    assert usage.total == HARD_BUDGET
    assert usage.by_category["notify_send"] == HARD_BUDGET
    assert usage.by_category["token"] == 0


@override_settings(
    EASYAUTH_DINGTALK_DAILY_CALL_BUDGET=1,
    EASYAUTH_DINGTALK_DAILY_RECONCILE_CALL_BUDGET=1,
)
def test_exceeded_error_log_is_deduped_per_day_and_category(
    caplog: pytest.LogCaptureFixture,
) -> None:
    record_and_check("token")
    logger_name = budget_module.logger.name
    with caplog.at_level(logging.ERROR, logger=logger_name):
        with pytest.raises(DingTalkCallBudgetExceededError):
            record_and_check("token")
        with pytest.raises(DingTalkCallBudgetExceededError):
            record_and_check("token")
        with pytest.raises(DingTalkCallBudgetExceededError):
            record_and_check("approval")
    messages = [record.getMessage() for record in caplog.records if record.levelno == logging.ERROR]
    assert len(messages) == 2
    assert sum("category=token" in message for message in messages) == 1
    assert sum("category=approval" in message for message in messages) == 1


def test_cache_failure_allows_call(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(budget_module, "cache", _FailingCache())
    with caplog.at_level(logging.WARNING, logger=budget_module.logger.name):
        record_and_check("probe")
    assert "计量缓存失败" in caplog.text
    assert "放行本次调用" in caplog.text


def test_budget_health_thresholds() -> None:
    healthy = _usage(total=0)
    assert budget_health_status(healthy) == "healthy"
    assert budget_health_reason(healthy) == ""
    assert "今日调用 0/5000" in format_usage_summary(healthy)

    warning_hard = _usage(total=4000)
    assert budget_health_status(warning_hard) == "warning"
    assert "80%" in budget_health_reason(warning_hard)

    warning_reconcile = _usage(total=1000, reconcile=1000)
    assert budget_health_status(warning_reconcile) == "warning"
    assert "回执对账日预算已耗尽" in budget_health_reason(warning_reconcile)

    exhausted = _usage(total=5000)
    assert budget_health_status(exhausted) == "unhealthy"
    assert "硬预算已耗尽" in budget_health_reason(exhausted)


def test_parse_positive_int_setting_rejects_non_positive() -> None:
    assert parse_positive_int_setting("EASYAUTH_DINGTALK_DAILY_CALL_BUDGET", "5000") == 5000
    with pytest.raises(ImproperlyConfigured, match="大于 0"):
        _ = parse_positive_int_setting("EASYAUTH_DINGTALK_DAILY_CALL_BUDGET", "0")
    with pytest.raises(ImproperlyConfigured, match="大于 0"):
        _ = parse_positive_int_setting("EASYAUTH_DINGTALK_DAILY_RECONCILE_CALL_BUDGET", "-1")
    with pytest.raises(ImproperlyConfigured, match="大于 0"):
        _ = parse_positive_int_setting("EASYAUTH_DINGTALK_DAILY_CALL_BUDGET", "x")


def test_unknown_category_fails_fast() -> None:
    unknown = cast("DingTalkCallCategory", "not-a-category")
    with pytest.raises(ValueError, match="未知的钉钉调用类别"):
        record_and_check(unknown)
