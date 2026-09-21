from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from json import loads
from typing import TYPE_CHECKING, Final, Protocol, cast, final, override
from urllib.parse import quote_plus

from dingtalk_stream import DingTalkStreamClient
from websockets.asyncio.client import connect as websocket_connect

if TYPE_CHECKING:
    import threading
    from collections.abc import AsyncIterator, Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

logger = logging.getLogger(__name__)

STREAM_RECONNECT_INITIAL_SECONDS: Final = 5.0
STREAM_RECONNECT_MAX_SECONDS: Final = 300.0
STREAM_RECONNECT_HEALTHY_SECONDS: Final = 60.0
STREAM_RECONNECT_JITTER_RATIO: Final = 0.2
_UNIT_INTERVAL_RESOLUTION: Final = 1_000_000

STREAM_OPEN_FAILED_MESSAGE: Final = "钉钉 Stream 打开连接失败。"
STREAM_INVALID_MESSAGE_MESSAGE: Final = "钉钉 Stream 收到非文本消息, 无法解析。"
STREAM_START_FOREVER_FORBIDDEN_MESSAGE: Final = (
    "钉钉 Stream 禁止使用 SDK 的 start_forever 固定重连, 必须走监督循环。"
)
STREAM_CLIENT_TYPE_MESSAGE: Final = (
    "钉钉 Stream 会话必须使用 SingleSessionDingTalkStreamClient, "
    "禁止 SDK 默认 start() 内循环。"
)
STREAM_JITTER_UNIT_MESSAGE: Final = "钉钉 Stream 重连抖动采样必须落在 [0, 1) 区间。"
STREAM_RECONNECT_STREAK_MESSAGE: Final = "钉钉 Stream 短会话计数不能为负数。"


class StreamOpenConnectionError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(STREAM_OPEN_FAILED_MESSAGE)


class StreamInvalidMessageError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(STREAM_INVALID_MESSAGE_MESSAGE)


class StreamStartForeverForbiddenError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(STREAM_START_FOREVER_FORBIDDEN_MESSAGE)


class StreamClientTypeError(TypeError):
    def __init__(self) -> None:
        super().__init__(STREAM_CLIENT_TYPE_MESSAGE)


class StreamReconnectContractError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class _DingTalkSdkClient(Protocol):
    def pre_start(self) -> None: ...

    def open_connection(self) -> object: ...

    async def keepalive(self, websocket: object, ping_interval: int = 60) -> None: ...

    async def background_task(self, json_message: object) -> None: ...


def default_reconnect_unit() -> float:
    return secrets.randbelow(_UNIT_INTERVAL_RESOLUTION) / _UNIT_INTERVAL_RESOLUTION


@dataclass(frozen=True, slots=True)
class StreamSupervisorHooks:
    """监督循环的时钟、睡眠、停止条件与抖动采样; 可注入以便测试。"""

    should_stop: Callable[[], bool]
    sleep: Callable[[float], None] = field(default=time.sleep)
    clock: Callable[[], float] = field(default=time.monotonic)
    unit_interval: Callable[[], float] = field(default=default_reconnect_unit)


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


def supervisor_hooks_from_event(stop: threading.Event) -> StreamSupervisorHooks:
    def sleep(seconds: float) -> None:
        _ = stop.wait(seconds)

    return StreamSupervisorHooks(should_stop=stop.is_set, sleep=sleep)


def bind_stream_session(client: DingTalkStreamClient) -> Callable[[], None]:
    def session() -> None:
        run_one_stream_session(client)

    return session


def run_one_stream_session(client: DingTalkStreamClient) -> None:
    if not isinstance(client, SingleSessionDingTalkStreamClient):
        raise StreamClientTypeError
    asyncio.run(client.start())


def run_supervised_stream(
    session: Callable[[], None],
    hooks: StreamSupervisorHooks,
) -> None:
    streak = 0
    while not hooks.should_stop():
        started = hooks.clock()
        if not _invoke_stream_session(session):
            return
        if hooks.should_stop():
            return
        elapsed = hooks.clock() - started
        streak, delay = _plan_reconnect(streak, elapsed, hooks.unit_interval())
        logger.warning(
            "钉钉 Stream 将重连: 第 %s 次尝试, 下次等待 %.1f 秒",
            streak,
            delay,
        )
        if not _sleep_or_stop(hooks, delay):
            return


def _plan_reconnect(streak: int, elapsed: float, unit: float) -> tuple[int, float]:
    next_streak = 0 if elapsed >= STREAM_RECONNECT_HEALTHY_SECONDS else streak
    return next_streak + 1, reconnect_sleep_seconds(next_streak, unit)


def _invoke_stream_session(session: Callable[[], None]) -> bool:
    try:
        session()
    except KeyboardInterrupt:
        logger.info("钉钉 Stream 收到中断, 停止重连")
        return False
    except Exception as error:
        if isinstance(error, StreamClientTypeError):
            raise
        logger.exception("钉钉 Stream 会话异常结束, 将按退避重连")
    return True


def _sleep_or_stop(hooks: StreamSupervisorHooks, delay: float) -> bool:
    try:
        hooks.sleep(delay)
    except KeyboardInterrupt:
        logger.info("钉钉 Stream 收到中断, 停止重连")
        return False
    return not hooks.should_stop()


@final
class SingleSessionDingTalkStreamClient(DingTalkStreamClient):
    """一次 start() 只打开一次连接并消费一个 WebSocket 会话, 不在 SDK 内重试。"""

    websocket: object | None = None

    @override
    def start_forever(self) -> None:
        raise StreamStartForeverForbiddenError

    @override
    async def start(self) -> None:
        sdk = cast("_DingTalkSdkClient", cast("object", self))
        sdk.pre_start()
        connection = sdk.open_connection()
        if connection is None:
            raise StreamOpenConnectionError
        await _consume_websocket(self, _websocket_uri(connection), sdk)


def _websocket_uri(connection: object) -> str:
    if not isinstance(connection, dict):
        raise StreamOpenConnectionError
    payload = cast("dict[str, object]", connection)
    endpoint = payload.get("endpoint")
    ticket = payload.get("ticket")
    if not isinstance(endpoint, str) or not endpoint:
        raise StreamOpenConnectionError
    if not isinstance(ticket, str) or not ticket:
        raise StreamOpenConnectionError
    return f"{endpoint}?ticket={quote_plus(ticket)}"


async def _consume_websocket(
    client: SingleSessionDingTalkStreamClient,
    uri: str,
    sdk: _DingTalkSdkClient,
) -> None:
    tasks: set[asyncio.Task[None]] = set()
    async with _websocket_session(uri) as websocket:
        client.websocket = websocket
        _track_task(
            tasks,
            cast("Coroutine[object, object, None]", sdk.keepalive(websocket)),
        )
        async for raw_message in _iter_websocket_messages(websocket):
            _track_task(
                tasks,
                cast(
                    "Coroutine[object, object, None]",
                    sdk.background_task(_decode_stream_message(raw_message)),
                ),
            )


def _websocket_session(uri: str) -> AbstractAsyncContextManager[object]:
    return cast("AbstractAsyncContextManager[object]", websocket_connect(uri))


def _iter_websocket_messages(websocket: object) -> AsyncIterator[object]:
    return cast("AsyncIterator[object]", websocket)


def _decode_stream_message(raw_message: object) -> object:
    if not isinstance(raw_message, str | bytes):
        raise StreamInvalidMessageError
    return cast("object", loads(raw_message))


def _track_task(
    tasks: set[asyncio.Task[None]],
    coro: Coroutine[object, object, None],
) -> None:
    task = asyncio.create_task(coro)
    tasks.add(task)
    task.add_done_callback(tasks.discard)
