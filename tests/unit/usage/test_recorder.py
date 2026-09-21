from __future__ import annotations

import logging
import sys
import types
from typing import TYPE_CHECKING

import pytest
from django.core.cache import cache
from django.utils import timezone

from easyauth.integrations.dingtalk.errors import (
    DingTalkApiUnavailableError,
    DingTalkCallBudgetExceededError,
)
from easyauth.usage import recorder as recorder_module
from easyauth.usage.recorder import current_hour_counts, record, record_and_check

if TYPE_CHECKING:
    from collections.abc import Callable

    from easyauth.usage.registry import UsageCategory


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


def _patch_decide(
    monkeypatch: pytest.MonkeyPatch,
    *,
    allowed: bool | Callable[[UsageCategory], bool],
) -> None:
    name = "easyauth.usage.enforcement"
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)

    def _decide(spec: UsageCategory) -> bool:
        if isinstance(allowed, bool):
            return allowed
        return allowed(spec)

    monkeypatch.setattr(f"{name}.decide", _decide, raising=False)


def _day_billed() -> int:
    key = f"usage:day:{timezone.localdate().strftime('%Y%m%d')}:api_billed"
    value = cache.get(key)
    return 0 if value is None else int(value)


def test_incr_add_on_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_decide(monkeypatch, allowed=True)
    record_and_check("token")
    record_and_check("token")
    record_and_check("notify_send")
    assert current_hour_counts()["token"] == (2, 0)
    assert current_hour_counts()["notify_send"] == (1, 0)
    assert _day_billed() == 1


def test_record_never_refuses_and_does_not_touch_day_billed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_decide(monkeypatch, allowed=False)
    record("webhook_callback", count=3)
    assert current_hour_counts()["webhook_callback"] == (3, 0)
    assert _day_billed() == 0


def test_cache_failure_allows_and_never_raises(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _patch_decide(monkeypatch, allowed=True)
    monkeypatch.setattr(recorder_module, "cache", _FailingCache())
    with caplog.at_level(logging.WARNING, logger=recorder_module.logger.name):
        record_and_check("probe")
        record("notify_send")
    assert "用量计数缓存失败" in caplog.text
    assert "放行本次调用" in caplog.text


def test_refusal_increments_blocked_without_counting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_decide(monkeypatch, allowed=False)
    with pytest.raises(DingTalkCallBudgetExceededError, match="notify_send") as exc_info:
        record_and_check("notify_send")
    assert isinstance(exc_info.value, DingTalkApiUnavailableError)
    assert current_hour_counts()["notify_send"] == (0, 1)
    assert _day_billed() == 0


def test_unknown_category_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_decide(monkeypatch, allowed=True)
    with pytest.raises(KeyError, match="未知的用量类别"):
        record_and_check("not-a-category")
