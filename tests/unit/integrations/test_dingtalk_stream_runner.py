from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field

import pytest
from dingtalk_stream import Credential, DingTalkStreamClient

from easyauth.integrations.dingtalk.stream_runner import (
    STREAM_RECONNECT_HEALTHY_SECONDS,
    STREAM_RECONNECT_INITIAL_SECONDS,
    STREAM_RECONNECT_JITTER_RATIO,
    STREAM_RECONNECT_MAX_SECONDS,
    SingleSessionDingTalkStreamClient,
    StreamClientTypeError,
    StreamOpenConnectionError,
    StreamReconnectContractError,
    StreamStartForeverForbiddenError,
    StreamSupervisorHooks,
    apply_reconnect_jitter,
    reconnect_base_seconds,
    reconnect_sleep_seconds,
    run_one_stream_session,
    run_supervised_stream,
    supervisor_hooks_from_event,
)
from easyauth.integrations.management.commands import run_dingtalk_stream as command_module
from easyauth.integrations.management.commands.run_dingtalk_stream import Command

EXPECTED_BASE_SEQUENCE = (5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 300.0, 300.0)
SHORT_SESSION_SECONDS = 1.0
JUST_UNDER_HEALTHY_SECONDS = STREAM_RECONNECT_HEALTHY_SECONDS - 0.1
JITTER_UNIT_HALF = 0.5
JITTER_UNIT_NEAR_ONE = 0.999
CAP_STREAK = 6


@dataclass(slots=True)
class _Probe:
    sessions: int = 0
    sleeps: list[float] = field(default_factory=list)
    stop_after_sleeps: int = 0
    stop_after_sessions: int = 0
    elapsed: float | list[float] = SHORT_SESSION_SECONDS
    now: float = 0.0
    session_error: BaseException | None = None

    def clock(self) -> float:
        return self.now

    def should_stop(self) -> bool:
        if self.stop_after_sessions > 0 and self.sessions >= self.stop_after_sessions:
            return True
        return self.stop_after_sleeps > 0 and len(self.sleeps) >= self.stop_after_sleeps

    def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)

    def session(self) -> None:
        self.sessions += 1
        duration = (
            self.elapsed[self.sessions - 1] if isinstance(self.elapsed, list) else self.elapsed
        )
        self.now += duration
        if self.session_error is not None:
            raise self.session_error

    def run(self, *, unit: float = 0.0) -> None:
        run_supervised_stream(
            self.session,
            StreamSupervisorHooks(
                should_stop=self.should_stop,
                sleep=self.sleep,
                clock=self.clock,
                unit_interval=lambda: unit,
            ),
        )


def test_backoff_sequence_is_five_doubling_to_cap() -> None:
    assert tuple(reconnect_base_seconds(streak) for streak in range(8)) == EXPECTED_BASE_SEQUENCE


def test_backoff_cap_stays_at_300() -> None:
    assert reconnect_base_seconds(CAP_STREAK) == STREAM_RECONNECT_MAX_SECONDS
    assert reconnect_base_seconds(CAP_STREAK + 4) == STREAM_RECONNECT_MAX_SECONDS


def test_jitter_bounds_are_zero_to_ratio() -> None:
    base = STREAM_RECONNECT_INITIAL_SECONDS
    assert apply_reconnect_jitter(base, 0.0) == base
    upper = apply_reconnect_jitter(base, JITTER_UNIT_NEAR_ONE)
    assert base < upper < base * (1.0 + STREAM_RECONNECT_JITTER_RATIO)
    assert upper == base * (1.0 + STREAM_RECONNECT_JITTER_RATIO * JITTER_UNIT_NEAR_ONE)


def test_jitter_does_not_lift_sleep_above_cap() -> None:
    assert reconnect_sleep_seconds(CAP_STREAK, JITTER_UNIT_NEAR_ONE) == STREAM_RECONNECT_MAX_SECONDS


def test_invalid_jitter_unit_fails_fast() -> None:
    with pytest.raises(StreamReconnectContractError, match="抖动采样"):
        apply_reconnect_jitter(STREAM_RECONNECT_INITIAL_SECONDS, 1.0)
    with pytest.raises(StreamReconnectContractError, match="抖动采样"):
        apply_reconnect_jitter(STREAM_RECONNECT_INITIAL_SECONDS, -0.01)
    with pytest.raises(StreamReconnectContractError, match="短会话计数"):
        reconnect_base_seconds(-1)


def test_supervised_loop_sleeps_exponential_sequence() -> None:
    probe = _Probe(stop_after_sleeps=len(EXPECTED_BASE_SEQUENCE))
    probe.run()
    assert probe.sleeps == list(EXPECTED_BASE_SEQUENCE)
    assert probe.sessions == len(EXPECTED_BASE_SEQUENCE)


def test_supervised_loop_applies_jitter_within_bounds() -> None:
    probe = _Probe(stop_after_sleeps=1)
    probe.run(unit=JITTER_UNIT_HALF)
    expected = STREAM_RECONNECT_INITIAL_SECONDS * (
        1.0 + STREAM_RECONNECT_JITTER_RATIO * JITTER_UNIT_HALF
    )
    assert probe.sleeps == [expected]


def test_healthy_session_resets_backoff() -> None:
    probe = _Probe(
        elapsed=[
            SHORT_SESSION_SECONDS,
            SHORT_SESSION_SECONDS,
            STREAM_RECONNECT_HEALTHY_SECONDS,
            SHORT_SESSION_SECONDS,
        ],
        stop_after_sessions=4,
    )
    probe.run()
    assert probe.sleeps == [5.0, 10.0, 5.0]


def test_just_under_healthy_window_does_not_reset() -> None:
    probe = _Probe(
        elapsed=[JUST_UNDER_HEALTHY_SECONDS, SHORT_SESSION_SECONDS, SHORT_SESSION_SECONDS],
        stop_after_sessions=3,
    )
    probe.run()
    assert probe.sleeps == [5.0, 10.0]


def test_short_session_does_not_reset_backoff() -> None:
    probe = _Probe(elapsed=SHORT_SESSION_SECONDS, stop_after_sessions=4)
    probe.run()
    assert probe.sleeps == [5.0, 10.0, 20.0]


def test_clean_exit_when_already_stopped() -> None:
    probe = _Probe()
    run_supervised_stream(
        probe.session,
        StreamSupervisorHooks(
            should_stop=lambda: True,
            sleep=probe.sleep,
            clock=probe.clock,
            unit_interval=lambda: 0.0,
        ),
    )
    assert probe.sessions == 0
    assert probe.sleeps == []


def test_clean_exit_after_session_sets_stop() -> None:
    probe = _Probe(stop_after_sessions=1)
    probe.run()
    assert probe.sessions == 1
    assert probe.sleeps == []


def test_keyboard_interrupt_stops_without_reconnect() -> None:
    probe = _Probe(session_error=KeyboardInterrupt(), stop_after_sleeps=3)
    probe.run()
    assert probe.sessions == 1
    assert probe.sleeps == []


def test_session_exception_reconnects() -> None:
    probe = _Probe(session_error=RuntimeError("ws down"), stop_after_sleeps=2)
    probe.run()
    assert probe.sessions == 2
    assert probe.sleeps == [5.0, 10.0]


def test_wrong_client_type_does_not_reconnect() -> None:
    probe = _Probe(stop_after_sleeps=3)

    def session() -> None:
        probe.session()
        raise StreamClientTypeError

    with pytest.raises(StreamClientTypeError):
        run_supervised_stream(
            session,
            StreamSupervisorHooks(
                should_stop=probe.should_stop,
                sleep=probe.sleep,
                clock=probe.clock,
                unit_interval=lambda: 0.0,
            ),
        )
    assert probe.sessions == 1
    assert probe.sleeps == []


def test_reconnect_log_includes_attempt_and_delay(
    caplog: pytest.LogCaptureFixture,
) -> None:
    probe = _Probe(stop_after_sleeps=2)
    with caplog.at_level("WARNING"):
        probe.run()
    assert "第 1 次尝试" in caplog.text
    assert "下次等待 5.0 秒" in caplog.text
    assert "第 2 次尝试" in caplog.text
    assert "下次等待 10.0 秒" in caplog.text


def test_event_sleep_returns_immediately_when_stopped() -> None:
    stop = threading.Event()
    stop.set()
    hooks = supervisor_hooks_from_event(stop)
    hooks.sleep(STREAM_RECONNECT_MAX_SECONDS)
    assert hooks.should_stop()


def test_start_forever_is_forbidden() -> None:
    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    with pytest.raises(StreamStartForeverForbiddenError, match="start_forever"):
        client.start_forever()


def test_run_one_session_rejects_sdk_default_client() -> None:
    client = DingTalkStreamClient(Credential("app-key", "app-secret"))
    with pytest.raises(StreamClientTypeError, match="SingleSessionDingTalkStreamClient"):
        run_one_stream_session(client)


def test_single_session_start_fails_fast_when_open_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    monkeypatch.setattr(client, "open_connection", lambda: None)
    sleeps: list[float] = []

    async def fail_if_slept(_delay: float) -> None:
        sleeps.append(_delay)
        message = "single-session start must not retry inside the SDK loop"
        raise AssertionError(message)

    monkeypatch.setattr(asyncio, "sleep", fail_if_slept)
    with pytest.raises(StreamOpenConnectionError, match="打开连接失败"):
        asyncio.run(client.start())
    assert sleeps == []


def test_single_session_start_fails_fast_on_incomplete_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    monkeypatch.setattr(client, "open_connection", lambda: {"endpoint": "wss://example.test"})
    with pytest.raises(StreamOpenConnectionError, match="打开连接失败"):
        asyncio.run(client.start())


def test_command_uses_supervised_loop_not_sdk_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _Client:
        def start_forever(self) -> None:
            calls.append("forever")

    monkeypatch.setattr(command_module, "build_stream_client", lambda: _Client())
    monkeypatch.setattr(command_module, "_install_shutdown_signals", lambda _stop: None)
    monkeypatch.setattr(command_module, "heartbeat_loop", lambda _stop: None)

    def fake_supervised(session: object, hooks: object) -> None:
        del session, hooks
        calls.append("supervised")

    monkeypatch.setattr(command_module, "run_supervised_stream", fake_supervised)
    Command().handle()
    assert calls == ["supervised"]
