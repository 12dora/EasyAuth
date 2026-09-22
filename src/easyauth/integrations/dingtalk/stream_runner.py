from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal

from easyauth.integrations.dingtalk.errors import DingTalkCallBudgetExceededError
from easyauth.integrations.dingtalk.stream_session import (
    STREAM_OPEN_CONNECT_TIMEOUT_SECONDS,
    STREAM_OPEN_FAILED_MESSAGE,
    STREAM_OPEN_READ_TIMEOUT_SECONDS,
    STREAM_PAUSED_CLOSE_MESSAGE,
    STREAM_SESSION_POLL_SECONDS,
    SingleSessionDingTalkStreamClient,
    StreamClientTypeError,
    StreamInvalidMessageError,
    StreamOpenConnectionError,
    StreamStartForeverForbiddenError,
    run_one_stream_session,
)

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    from dingtalk_stream import DingTalkStreamClient

logger = logging.getLogger(__name__)

STREAM_RECONNECT_INITIAL_SECONDS: Final = 5.0
STREAM_RECONNECT_MAX_SECONDS: Final = 300.0
STREAM_RECONNECT_HEALTHY_SECONDS: Final = 60.0
STREAM_RECONNECT_JITTER_RATIO: Final = 0.2
STREAM_PAUSE_POLL_SECONDS: Final = 30.0
_UNIT_INTERVAL_RESOLUTION: Final = 1_000_000

STREAM_JITTER_UNIT_MESSAGE: Final = "钉钉 Stream 重连抖动采样必须落在 [0, 1) 区间。"
STREAM_RECONNECT_STREAK_MESSAGE: Final = "钉钉 Stream 短会话计数不能为负数。"
STREAM_PAUSED_SKIP_OPEN_MESSAGE: Final = "钉钉 Stream 已按用量策略暂停, 暂不打开连接。"
STREAM_OPEN_REFUSED_MESSAGE: Final = "钉钉 Stream 打开连接被用量策略拒绝, 将按退避重连。"
STREAM_POLICY_CHECK_FAILED_MESSAGE: Final = "钉钉 Stream 用量策略查询失败, 将按退避重连。"
STREAM_INTERRUPTED_MESSAGE: Final = "钉钉 Stream 收到中断, 停止重连"
_FAILED_SESSION_SECONDS: Final = 0.0

type _StreamPolicy = Literal["run", "pause", "error", "stop"]

__all__ = (
    "STREAM_OPEN_CONNECT_TIMEOUT_SECONDS",
    "STREAM_OPEN_FAILED_MESSAGE",
    "STREAM_OPEN_READ_TIMEOUT_SECONDS",
    "STREAM_OPEN_REFUSED_MESSAGE",
    "STREAM_PAUSED_CLOSE_MESSAGE",
    "STREAM_PAUSED_SKIP_OPEN_MESSAGE",
    "STREAM_PAUSE_POLL_SECONDS",
    "STREAM_POLICY_CHECK_FAILED_MESSAGE",
    "STREAM_RECONNECT_HEALTHY_SECONDS",
    "STREAM_RECONNECT_INITIAL_SECONDS",
    "STREAM_RECONNECT_JITTER_RATIO",
    "STREAM_RECONNECT_MAX_SECONDS",
    "STREAM_SESSION_POLL_SECONDS",
    "SingleSessionDingTalkStreamClient",
    "StreamClientTypeError",
    "StreamInvalidMessageError",
    "StreamOpenConnectionError",
    "StreamReconnectContractError",
    "StreamStartForeverForbiddenError",
    "StreamSupervisorHooks",
    "apply_reconnect_jitter",
    "bind_stream_session",
    "reconnect_base_seconds",
    "reconnect_sleep_seconds",
    "run_one_stream_session",
    "run_supervised_stream",
    "supervisor_hooks_from_event",
)


class StreamReconnectContractError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def default_reconnect_unit() -> float:
    return secrets.randbelow(_UNIT_INTERVAL_RESOLUTION) / _UNIT_INTERVAL_RESOLUTION


def _stream_always_run() -> bool:
    return True


@dataclass(frozen=True, slots=True)
class StreamSupervisorHooks:
    """监督循环的时钟、睡眠、停止条件与抖动采样; 可注入以便测试。"""

    should_stop: Callable[[], bool]
    sleep: Callable[[float], None] = field(default=time.sleep)
    clock: Callable[[], float] = field(default=time.monotonic)
    unit_interval: Callable[[], float] = field(default=default_reconnect_unit)
    stream_should_run: Callable[[], bool] = field(default=_stream_always_run)
    pause_poll_seconds: float = STREAM_PAUSE_POLL_SECONDS


def reconnect_base_seconds(short_session_streak: int) -> float:
    if short_session_streak < 0:
        raise StreamReconnectContractError(STREAM_RECONNECT_STREAK_MESSAGE)
    delay = STREAM_RECONNECT_INITIAL_SECONDS
    for _ in range(short_session_streak):
        delay = min(delay * 2.0, STREAM_RECONNECT_MAX_SECONDS)
    return delay


def apply_reconnect_jitter(base_seconds: float, unit: float) -> float:
    if unit < 0.0 or unit >= 1.0:
        raise StreamReconnectContractError(STREAM_JITTER_UNIT_MESSAGE)
    return base_seconds * (1.0 + STREAM_RECONNECT_JITTER_RATIO * unit)


def reconnect_sleep_seconds(short_session_streak: int, unit: float) -> float:
    jittered = apply_reconnect_jitter(reconnect_base_seconds(short_session_streak), unit)
    return min(jittered, STREAM_RECONNECT_MAX_SECONDS)


def supervisor_hooks_from_event(
    stop: threading.Event,
    *,
    stream_should_run: Callable[[], bool] = _stream_always_run,
) -> StreamSupervisorHooks:
    def sleep(seconds: float) -> None:
        _ = stop.wait(seconds)

    return StreamSupervisorHooks(
        should_stop=stop.is_set,
        sleep=sleep,
        stream_should_run=stream_should_run,
    )


def bind_stream_session(
    client: DingTalkStreamClient,
    *,
    stream_should_run: Callable[[], bool] | None = None,
    record_stream_open: Callable[[], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Callable[[], float]:
    if isinstance(client, SingleSessionDingTalkStreamClient):
        if stream_should_run is not None:
            client.stream_should_run = stream_should_run
        if record_stream_open is not None:
            client.record_stream_open = record_stream_open
        if should_stop is not None:
            client.session_should_stop = should_stop

    def session() -> float:
        return _websocket_seconds_after_session(client)

    return session


@dataclass(slots=True)
class _SupervisorLoop:
    streak: int = 0
    pause_logged: bool = False


def run_supervised_stream(
    session: Callable[[], float],
    hooks: StreamSupervisorHooks,
) -> None:
    state = _SupervisorLoop()
    while not hooks.should_stop():
        if not _advance_supervisor(session, hooks, state):
            return


def _advance_supervisor(
    session: Callable[[], float],
    hooks: StreamSupervisorHooks,
    state: _SupervisorLoop,
) -> bool:
    policy = _read_stream_policy(hooks)
    if policy == "stop":
        return False
    if policy == "error":
        return _reconnect_after(hooks, state, _FAILED_SESSION_SECONDS)
    if policy == "pause":
        return _wait_while_paused(hooks, state)
    return _open_and_maybe_reconnect(session, hooks, state)


def _read_stream_policy(hooks: StreamSupervisorHooks) -> _StreamPolicy:
    try:
        return "run" if hooks.stream_should_run() else "pause"
    except KeyboardInterrupt:
        logger.info(STREAM_INTERRUPTED_MESSAGE)
        return "stop"
    except Exception:
        logger.exception(STREAM_POLICY_CHECK_FAILED_MESSAGE)
        return "error"


def _wait_while_paused(hooks: StreamSupervisorHooks, state: _SupervisorLoop) -> bool:
    state.pause_logged = _log_stream_paused_once(already_logged=state.pause_logged)
    state.streak = 0
    return _sleep_or_stop(hooks, hooks.pause_poll_seconds)


def _open_and_maybe_reconnect(
    session: Callable[[], float],
    hooks: StreamSupervisorHooks,
    state: _SupervisorLoop,
) -> bool:
    state.pause_logged = False
    connected = _invoke_stream_session(session)
    if connected is None:
        return False
    if hooks.should_stop():
        return True
    return _reconnect_after_open(hooks, state, connected)


def _reconnect_after_open(
    hooks: StreamSupervisorHooks,
    state: _SupervisorLoop,
    connected: float,
) -> bool:
    policy = _read_stream_policy(hooks)
    if policy == "stop":
        return False
    if policy == "pause":
        return True
    elapsed = _FAILED_SESSION_SECONDS if policy == "error" else connected
    return _reconnect_after(hooks, state, elapsed)


def _reconnect_after(
    hooks: StreamSupervisorHooks,
    state: _SupervisorLoop,
    elapsed: float,
) -> bool:
    state.pause_logged = False
    state.streak, delay = _plan_reconnect(state.streak, elapsed, hooks.unit_interval())
    logger.warning(
        "钉钉 Stream 将重连: 第 %s 次尝试, 下次等待 %.1f 秒",
        state.streak,
        delay,
    )
    return _sleep_or_stop(hooks, delay)


def _plan_reconnect(streak: int, elapsed: float, unit: float) -> tuple[int, float]:
    next_streak = 0 if elapsed >= STREAM_RECONNECT_HEALTHY_SECONDS else streak
    return next_streak + 1, reconnect_sleep_seconds(next_streak, unit)


def _websocket_seconds_after_session(client: DingTalkStreamClient) -> float:
    try:
        run_one_stream_session(client)
    except (KeyboardInterrupt, DingTalkCallBudgetExceededError, StreamClientTypeError):
        raise
    except Exception:
        logger.exception("钉钉 Stream 会话异常结束, 将按退避重连")
    if not isinstance(client, SingleSessionDingTalkStreamClient):
        raise StreamClientTypeError
    return client.last_websocket_seconds


def _log_stream_paused_once(*, already_logged: bool) -> bool:
    if not already_logged:
        logger.warning(STREAM_PAUSED_SKIP_OPEN_MESSAGE)
    return True


def _invoke_stream_session(session: Callable[[], float]) -> float | None:
    try:
        return session()
    except KeyboardInterrupt:
        logger.info(STREAM_INTERRUPTED_MESSAGE)
        return None
    except DingTalkCallBudgetExceededError:
        logger.warning(STREAM_OPEN_REFUSED_MESSAGE)
        return 0.0
    except StreamClientTypeError:
        raise
    except Exception:
        logger.exception("钉钉 Stream 会话异常结束, 将按退避重连")
        return 0.0


def _sleep_or_stop(hooks: StreamSupervisorHooks, delay: float) -> bool:
    try:
        hooks.sleep(delay)
    except KeyboardInterrupt:
        logger.info(STREAM_INTERRUPTED_MESSAGE)
        return False
    return not hooks.should_stop()
