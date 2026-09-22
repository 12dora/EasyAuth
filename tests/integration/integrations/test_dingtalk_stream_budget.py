from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, cast

import pytest
from django.conf import settings
from django.core.cache import cache
from django.core.cache.backends import base as cache_base
from django.core.cache.backends import locmem as cache_locmem

from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryClient,
    AuthentikDirectoryUnavailableError,
)
from easyauth.integrations.authentik.directory_refresh import (
    DIRECTORY_REFRESH_MAX_RETRIES,
    REFRESH_ATTEMPT_COUNT,
    REFRESH_ATTEMPT_WORST_CASE_SECONDS,
    REFRESH_BROKER_DELAY_ALLOWANCE_SECONDS,
    REFRESH_MARKER_TTL_SECONDS,
    REFRESH_POLL_INTERVAL_SECONDS,
    REFRESH_RETRY_BACKOFF_BUDGET_SECONDS,
    REFRESH_RETRY_BUDGET_SECONDS,
    REFRESH_STATUS_HTTP_TIMEOUT_SECONDS,
    REFRESH_TTL_STORM_MULTIPLIER,
    REFRESH_WAIT_TIMEOUT_SECONDS,
    refresh_trigger_marker_cache_key,
)
from easyauth.integrations.authentik.directory_sync_types import AuthentikDirectorySyncResult
from easyauth.tasks import dingtalk_stream as tasks_module
from easyauth.tasks.dingtalk_stream import refresh_dingtalk_directory_task
from easyauth.tasks.dingtalk_stream_markers import (
    REFRESH_FOLLOWUP_CACHE_KEY_TEMPLATE,
    REFRESH_FOLLOWUP_FLAG_TTL_SECONDS,
    REFRESH_MAX_CONSECUTIVE_REQUEUES,
    REFRESH_RUNNING_LOCK_TTL_SECONDS,
    REFRESH_TASK_SOFT_TIME_LIMIT_SECONDS,
    REFRESH_TASK_TIME_LIMIT_SECONDS,
    REFRESH_USER_IDS_CACHE_KEY_TEMPLATE,
    accumulate_refresh_user_ids,
    claim_exhaustion_followup,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

pytestmark = pytest.mark.django_db

_LATE_FOLLOWUP_SLACK_SECONDS = 120
_MARKER_BASELINE = "2026-07-06T00:00:00+00:00"
_TASK_LOGGER = "easyauth.tasks.dingtalk_stream"


@dataclass(slots=True)
class _SendTaskRecorder:
    calls: list[tuple[str, tuple[object, ...], float | None]] = field(default_factory=list)
    task_kwargs: list[dict[str, object]] = field(default_factory=list)

    def enqueue_task(
        self,
        *,
        event_key: str,
        task_name: str,
        args: Sequence[object] = (),
        kwargs: dict[str, object] | None = None,
        countdown: float = 0,
    ) -> object:
        _ = event_key
        self.calls.append((task_name, tuple(args), countdown or None))
        self.task_kwargs.append(dict(kwargs or {}))
        return object()


@dataclass(slots=True)
class _RefreshRecorder:
    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    queued: bool = True
    error: str = ""

    def fake_refresh(
        self,
        _client: object,
        corp_id: str,
        **kwargs: object,
    ) -> AuthentikDirectorySyncResult | None:
        raw_ids = kwargs.get("user_ids", ())
        user_ids = tuple(cast("Sequence[str]", raw_ids))
        self.calls.append((corp_id, user_ids))
        if self.error:
            raise AuthentikDirectoryUnavailableError(self.error)
        if not self.queued:
            return None
        return AuthentikDirectorySyncResult(
            department_count=0,
            user_count=0,
            org_context_count=0,
            sync_state_count=0,
        )


@dataclass(slots=True)
class _CacheClock:
    # 先抓住真实 time.time, 再补丁 LocMem 的读写时钟, 避免 now 递归调用自己。
    offset: float = 0.0
    origin: Callable[[], float] = field(default=time.time, repr=False)

    def now(self) -> float:
        return self.origin() + self.offset

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 写入超时走 base.time, 判断过期走 locmem.time。
        monkeypatch.setattr(cache_base.time, "time", self.now)
        monkeypatch.setattr(cache_locmem.time, "time", self.now)

    def advance(self, seconds: float) -> None:
        self.offset += seconds


@pytest.fixture
def sent_tasks(monkeypatch: pytest.MonkeyPatch) -> _SendTaskRecorder:
    recorder = _SendTaskRecorder()
    monkeypatch.setattr(tasks_module, "enqueue_task", recorder.enqueue_task)
    return recorder


@pytest.fixture
def refresh_recorder(monkeypatch: pytest.MonkeyPatch) -> _RefreshRecorder:
    recorder = _RefreshRecorder()
    monkeypatch.setattr(tasks_module, "refresh_dingtalk_directory", recorder.fake_refresh)
    monkeypatch.setattr(tasks_module.AuthentikDirectoryClient, "from_settings", lambda: object())
    return recorder


def test_refresh_budget_constants_cover_worst_case_and_second_storm() -> None:
    timeout_default = next(
        item.default
        for item in fields(AuthentikDirectoryClient)
        if item.name == "timeout_seconds"
    )
    assert timeout_default == REFRESH_STATUS_HTTP_TIMEOUT_SECONDS
    assert settings.EASYAUTH_AUTHENTIK_OIDC_HTTP_TIMEOUT_SECONDS == (
        REFRESH_STATUS_HTTP_TIMEOUT_SECONDS
    )
    assert REFRESH_ATTEMPT_COUNT == DIRECTORY_REFRESH_MAX_RETRIES + 1 == 6
    assert (
        int(REFRESH_WAIT_TIMEOUT_SECONDS)
        + int(REFRESH_POLL_INTERVAL_SECONDS)
        + REFRESH_STATUS_HTTP_TIMEOUT_SECONDS
    ) == REFRESH_ATTEMPT_WORST_CASE_SECONDS
    assert REFRESH_ATTEMPT_WORST_CASE_SECONDS == 188
    assert REFRESH_RETRY_BACKOFF_BUDGET_SECONDS == 31
    assert REFRESH_BROKER_DELAY_ALLOWANCE_SECONDS == 300
    assert REFRESH_TTL_STORM_MULTIPLIER == 2
    expected_total = 6 * 188 + 31 + 300
    assert expected_total == REFRESH_RETRY_BUDGET_SECONDS
    assert 2 * expected_total == REFRESH_MARKER_TTL_SECONDS
    assert REFRESH_FOLLOWUP_FLAG_TTL_SECONDS == REFRESH_MARKER_TTL_SECONDS
    assert REFRESH_RETRY_BUDGET_SECONDS + _LATE_FOLLOWUP_SLACK_SECONDS < REFRESH_MARKER_TTL_SECONDS
    assert (
        REFRESH_TASK_SOFT_TIME_LIMIT_SECONDS
        < REFRESH_TASK_TIME_LIMIT_SECONDS
        < REFRESH_RUNNING_LOCK_TTL_SECONDS
        < REFRESH_RETRY_BUDGET_SECONDS
        < REFRESH_MARKER_TTL_SECONDS
    )
    assert refresh_dingtalk_directory_task.soft_time_limit == REFRESH_TASK_SOFT_TIME_LIMIT_SECONDS
    assert refresh_dingtalk_directory_task.time_limit == REFRESH_TASK_TIME_LIMIT_SECONDS


def test_followup_exhaustion_logs_once_and_does_not_enqueue(
    sent_tasks: _SendTaskRecorder,
    refresh_recorder: _RefreshRecorder,
    caplog: pytest.LogCaptureFixture,
) -> None:
    refresh_recorder.error = "upstream down"
    accumulate_refresh_user_ids("corp-1", ["u-hold"])
    refresh_dingtalk_directory_task.push_request(
        retries=DIRECTORY_REFRESH_MAX_RETRIES,
        called_directly=False,
    )
    try:
        with (
            caplog.at_level(logging.ERROR, logger=_TASK_LOGGER),
            pytest.raises(AuthentikDirectoryUnavailableError, match="upstream down"),
        ):
            _ = refresh_dingtalk_directory_task("corp-1", trailing=True, is_followup=True)
    finally:
        refresh_dingtalk_directory_task.pop_request()

    assert sent_tasks.calls == []
    errors = _task_errors(caplog)
    assert len(errors) == 1
    assert "不再安排下一次" in errors[0].getMessage()
    assert _pending_user_ids("corp-1") == ["u-hold"]


def test_followup_requeue_chain_stops_without_another_followup(
    sent_tasks: _SendTaskRecorder,
    refresh_recorder: _RefreshRecorder,
    caplog: pytest.LogCaptureFixture,
) -> None:
    refresh_recorder.queued = False
    accumulate_refresh_user_ids("corp-1", ["u-hold"])
    trailing = True
    is_followup = True
    with caplog.at_level(logging.ERROR, logger=_TASK_LOGGER):
        for _step in range(REFRESH_MAX_CONSECUTIVE_REQUEUES + 1):
            _ = refresh_dingtalk_directory_task(
                "corp-1",
                trailing=trailing,
                is_followup=is_followup,
            )
            trailing, is_followup = _latest_refresh_flags(sent_tasks)

    assert sent_tasks.task_kwargs == [{"is_followup": True}] * REFRESH_MAX_CONSECUTIVE_REQUEUES
    assert float(REFRESH_RETRY_BUDGET_SECONDS) not in [call[2] for call in sent_tasks.calls]
    errors = _task_errors(caplog)
    assert len(errors) == 1
    assert "不再安排下一次" in errors[0].getMessage()
    assert "已安排一次延迟补刷新" not in caplog.text
    assert _pending_user_ids("corp-1") == ["u-hold"]


def test_late_followup_still_sees_pending_user_ids(
    refresh_recorder: _RefreshRecorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _CacheClock()
    clock.install(monkeypatch)
    accumulate_refresh_user_ids("corp-1", ["u-late"])
    cache.set(
        "budget-probe",
        "1",
        timeout=REFRESH_RETRY_BUDGET_SECONDS + _LATE_FOLLOWUP_SLACK_SECONDS,
    )
    clock.advance(float(REFRESH_RETRY_BUDGET_SECONDS) + _LATE_FOLLOWUP_SLACK_SECONDS)

    assert cache.get("budget-probe") is None
    assert _pending_user_ids("corp-1") == ["u-late"]
    _ = refresh_dingtalk_directory_task("corp-1", trailing=True, is_followup=True)
    assert refresh_recorder.calls == [("corp-1", ("u-late",))]


def test_attempt_start_does_not_invent_missing_markers(
    refresh_recorder: _RefreshRecorder,
) -> None:
    refresh_recorder.error = "upstream down"
    accumulate_refresh_user_ids("corp-1", ["u-1"])
    with pytest.raises(AuthentikDirectoryUnavailableError, match="upstream down"):
        _ = refresh_dingtalk_directory_task("corp-1")
    assert cache.get(refresh_trigger_marker_cache_key("corp-1")) is None
    assert _followup_flag("corp-1") is None
    assert _pending_user_ids("corp-1") == ["u-1"]


def test_attempt_start_refreshes_trigger_marker_and_followup_flag(
    refresh_recorder: _RefreshRecorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _CacheClock()
    clock.install(monkeypatch)
    cache.set(
        refresh_trigger_marker_cache_key("corp-1"),
        {"baseline": _MARKER_BASELINE, "user_ids": ["u-1"]},
        timeout=REFRESH_MARKER_TTL_SECONDS,
    )
    accumulate_refresh_user_ids("corp-1", ["u-1"])
    assert claim_exhaustion_followup("corp-1") is True
    clock.advance(REFRESH_MARKER_TTL_SECONDS - 30)
    refresh_recorder.error = "upstream down"
    with pytest.raises(AuthentikDirectoryUnavailableError, match="upstream down"):
        _ = refresh_dingtalk_directory_task("corp-1")

    clock.advance(60)
    assert cache.get(refresh_trigger_marker_cache_key("corp-1")) == {
        "baseline": _MARKER_BASELINE,
        "user_ids": ["u-1"],
    }
    assert _followup_flag("corp-1") == "1"
    clock.advance(REFRESH_MARKER_TTL_SECONDS)
    assert cache.get(refresh_trigger_marker_cache_key("corp-1")) is None
    assert _followup_flag("corp-1") is None


def _latest_refresh_flags(sent_tasks: _SendTaskRecorder) -> tuple[bool, bool]:
    if not sent_tasks.task_kwargs:
        return False, False
    latest = sent_tasks.task_kwargs[-1]
    return latest.get("trailing") is True, latest.get("is_followup") is True


def _task_errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == _TASK_LOGGER and record.levelno == logging.ERROR
    ]


def _pending_user_ids(corp_id: str) -> list[str]:
    raw = cast("object", cache.get(REFRESH_USER_IDS_CACHE_KEY_TEMPLATE.format(corp_id=corp_id)))
    if raw is None:
        return []
    return list(cast("list[str]", raw))


def _followup_flag(corp_id: str) -> object:
    return cache.get(REFRESH_FOLLOWUP_CACHE_KEY_TEMPLATE.format(corp_id=corp_id))
