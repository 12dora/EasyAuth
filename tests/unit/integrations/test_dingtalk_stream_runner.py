from __future__ import annotations

import signal
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from dingtalk_stream import Credential

from easyauth.integrations.dingtalk.errors import DingTalkCallBudgetExceededError
from easyauth.integrations.dingtalk.stream_runner import (
    STREAM_PAUSE_POLL_SECONDS,
    STREAM_PAUSED_SKIP_OPEN_MESSAGE,
    STREAM_POLICY_CHECK_FAILED_MESSAGE,
    STREAM_RECONNECT_HEALTHY_SECONDS,
    STREAM_RECONNECT_INITIAL_SECONDS,
    STREAM_RECONNECT_JITTER_RATIO,
    STREAM_RECONNECT_MAX_SECONDS,
    StreamClientTypeError,
    StreamOpenConnectionError,
    StreamReconnectContractError,
    StreamSupervisorHooks,
    apply_reconnect_jitter,
    bind_stream_session,
    reconnect_base_seconds,
    reconnect_sleep_seconds,
    run_supervised_stream,
    supervisor_hooks_from_event,
)
from easyauth.integrations.dingtalk.stream_session import SingleSessionDingTalkStreamClient
from easyauth.integrations.management.commands import run_dingtalk_stream as command_module
from easyauth.integrations.management.commands.run_dingtalk_stream import Command

if TYPE_CHECKING:
    from collections.abc import Callable

EXPECTED_BASE_SEQUENCE = (5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 300.0, 300.0)
SHORT_SESSION_SECONDS = 1.0
JUST_UNDER_HEALTHY_SECONDS = STREAM_RECONNECT_HEALTHY_SECONDS - 0.1
JITTER_UNIT_HALF = 0.5
JITTER_UNIT_NEAR_ONE = 0.999
CAP_STREAK = 6
OPEN_HANG_WALL_SECONDS = 70.0


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

    def session(self) -> float:
        self.sessions += 1
        duration = (
            self.elapsed[self.sessions - 1] if isinstance(self.elapsed, list) else self.elapsed
        )
        self.now += duration
        if self.session_error is not None:
            raise self.session_error
        return duration

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
    # elapsed 是 WebSocket 已连接时长, 不是 open_connection 墙钟。
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

    def session() -> float:
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


def test_paused_stream_does_not_open_and_polls(
    caplog: pytest.LogCaptureFixture,
) -> None:
    probe = _Probe(stop_after_sleeps=2)
    with caplog.at_level("WARNING"):
        run_supervised_stream(
            probe.session,
            StreamSupervisorHooks(
                should_stop=probe.should_stop,
                sleep=probe.sleep,
                clock=probe.clock,
                unit_interval=lambda: 0.0,
                stream_should_run=lambda: False,
                pause_poll_seconds=STREAM_PAUSE_POLL_SECONDS,
            ),
        )
    assert probe.sessions == 0
    assert probe.sleeps == [STREAM_PAUSE_POLL_SECONDS, STREAM_PAUSE_POLL_SECONDS]
    assert caplog.text.count(STREAM_PAUSED_SKIP_OPEN_MESSAGE) == 1


def test_paused_stream_opens_after_resume() -> None:
    states = [False, False, True]

    def should_run() -> bool:
        return states.pop(0) if states else True

    probe = _Probe(stop_after_sessions=1)
    run_supervised_stream(
        probe.session,
        StreamSupervisorHooks(
            should_stop=probe.should_stop,
            sleep=probe.sleep,
            clock=probe.clock,
            unit_interval=lambda: 0.0,
            stream_should_run=should_run,
            pause_poll_seconds=STREAM_PAUSE_POLL_SECONDS,
        ),
    )
    assert probe.sessions == 1
    assert probe.sleeps == [STREAM_PAUSE_POLL_SECONDS, STREAM_PAUSE_POLL_SECONDS]


def test_policy_error_before_open_backs_off_and_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = {"n": 0}

    def should_run() -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            message = "redis down"
            raise RuntimeError(message)
        return True

    probe = _Probe(stop_after_sessions=1)
    with caplog.at_level("ERROR"):
        run_supervised_stream(probe.session, _policy_hooks(probe, should_run))
    assert probe.sessions == 1
    assert probe.sleeps == [STREAM_RECONNECT_INITIAL_SECONDS]
    assert calls["n"] == 2
    assert STREAM_POLICY_CHECK_FAILED_MESSAGE in caplog.text
    assert STREAM_PAUSED_SKIP_OPEN_MESSAGE not in caplog.text


def test_policy_error_after_session_backs_off_and_continues() -> None:
    calls = {"n": 0}

    def should_run() -> bool:
        calls["n"] += 1
        if calls["n"] == 2:
            message = "redis down"
            raise RuntimeError(message)
        return True

    probe = _Probe(stop_after_sessions=2)
    run_supervised_stream(probe.session, _policy_hooks(probe, should_run))
    assert probe.sessions == 2
    assert probe.sleeps == [STREAM_RECONNECT_INITIAL_SECONDS]
    assert calls["n"] == 3


def test_policy_keyboard_interrupt_stops_without_backoff() -> None:
    def should_run() -> bool:
        raise KeyboardInterrupt

    probe = _Probe(stop_after_sleeps=3)
    run_supervised_stream(probe.session, _policy_hooks(probe, should_run))
    assert probe.sessions == 0
    assert probe.sleeps == []


def test_policy_system_exit_escapes() -> None:
    def should_run() -> bool:
        raise SystemExit

    probe = _Probe(stop_after_sleeps=3)
    with pytest.raises(SystemExit):
        run_supervised_stream(probe.session, _policy_hooks(probe, should_run))
    assert probe.sessions == 0
    assert probe.sleeps == []


def _policy_hooks(probe: _Probe, should_run: Callable[[], bool]) -> StreamSupervisorHooks:
    return StreamSupervisorHooks(
        should_stop=probe.should_stop,
        sleep=probe.sleep,
        clock=probe.clock,
        unit_interval=lambda: 0.0,
        stream_should_run=should_run,
    )


def test_open_refusal_uses_reconnect_backoff(caplog: pytest.LogCaptureFixture) -> None:
    probe = _Probe(session_error=DingTalkCallBudgetExceededError(), stop_after_sleeps=2)
    with caplog.at_level("WARNING"):
        probe.run()
    assert probe.sessions == 2
    assert probe.sleeps == [5.0, 10.0]
    assert "用量策略拒绝" in caplog.text


def test_open_hang_timeout_does_not_reset_streak_when_wall_time_exceeds_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = {"t": 0.0}
    sleeps: list[float] = []

    def fake_open() -> dict[str, object]:
        now["t"] += OPEN_HANG_WALL_SECONDS
        raise StreamOpenConnectionError

    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    monkeypatch.setattr(client, "open_connection", fake_open)
    run_supervised_stream(
        bind_stream_session(client),
        StreamSupervisorHooks(
            should_stop=lambda: len(sleeps) >= 3,
            sleep=sleeps.append,
            clock=lambda: now["t"],
            unit_interval=lambda: 0.0,
        ),
    )
    assert sleeps == [5.0, 10.0, 20.0]
    assert now["t"] == OPEN_HANG_WALL_SECONDS * 3


def test_stop_during_backoff_sleep_skips_next_session() -> None:
    stopped = {"v": False}
    sleeps: list[float] = []
    sessions = {"n": 0}

    def session() -> float:
        sessions["n"] += 1
        return 0.0

    def sleep(delay: float) -> None:
        sleeps.append(delay)
        stopped["v"] = True

    run_supervised_stream(
        session,
        StreamSupervisorHooks(
            should_stop=lambda: stopped["v"],
            sleep=sleep,
            unit_interval=lambda: 0.0,
        ),
    )
    assert sessions["n"] == 1
    assert sleeps == [5.0]


def test_stop_while_policy_paused_exits_without_opening() -> None:
    stopped = {"v": False}
    sleeps: list[float] = []
    sessions = {"n": 0}

    def session() -> float:
        sessions["n"] += 1
        return 0.0

    def sleep(delay: float) -> None:
        sleeps.append(delay)
        stopped["v"] = True

    run_supervised_stream(
        session,
        StreamSupervisorHooks(
            should_stop=lambda: stopped["v"],
            sleep=sleep,
            unit_interval=lambda: 0.0,
            stream_should_run=lambda: False,
        ),
    )
    assert sessions["n"] == 0
    assert sleeps == [STREAM_PAUSE_POLL_SECONDS]


def test_sigterm_handler_only_sets_the_event() -> None:
    stop = threading.Event()
    handle = command_module.stop_only_signal_handler(stop)
    handle(signal.SIGTERM, None)
    assert stop.is_set()


def test_sigint_handler_only_sets_the_event() -> None:
    stop = threading.Event()
    handle = command_module.stop_only_signal_handler(stop)
    handle(signal.SIGINT, None)
    assert stop.is_set()


def test_command_wires_pause_and_open_metering(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _Client:
        def start_forever(self) -> None:
            return None

    monkeypatch.setattr(command_module, "build_stream_client", lambda: _Client())
    monkeypatch.setattr(command_module, "_install_shutdown_signals", lambda _stop: None)
    monkeypatch.setattr(command_module, "heartbeat_loop", lambda _stop: None)

    def fake_supervised(session: object, hooks: StreamSupervisorHooks) -> None:
        captured["hooks"] = hooks
        captured["session"] = session

    monkeypatch.setattr(command_module, "run_supervised_stream", fake_supervised)
    Command().handle()
    hooks = captured["hooks"]
    assert isinstance(hooks, StreamSupervisorHooks)
    assert hooks.stream_should_run is command_module.stream_should_run


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


def test_command_bind_passes_stop_event(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _Client:
        def start_forever(self) -> None:
            return None

    monkeypatch.setattr(command_module, "build_stream_client", lambda: _Client())
    monkeypatch.setattr(command_module, "_install_shutdown_signals", lambda _stop: None)
    monkeypatch.setattr(command_module, "heartbeat_loop", lambda _stop: None)

    def fake_bind(
        client: object,
        *,
        stream_should_run: object,
        record_stream_open: object,
        should_stop: object,
    ) -> object:
        del client, stream_should_run, record_stream_open
        captured["should_stop"] = should_stop
        return lambda: 0.0

    def fake_supervised(session: object, hooks: object) -> None:
        del session, hooks

    monkeypatch.setattr(command_module, "bind_stream_session", fake_bind)
    monkeypatch.setattr(command_module, "run_supervised_stream", fake_supervised)
    Command().handle()
    assert callable(captured["should_stop"])
