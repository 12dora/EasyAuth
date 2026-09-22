from __future__ import annotations

import asyncio
import inspect
import logging
import platform
import time
from dataclasses import dataclass
from http import HTTPStatus
from importlib.metadata import version as package_version
from json import dumps, loads
from typing import TYPE_CHECKING, Final, Protocol, cast, final, override
from urllib.parse import quote_plus

import requests
from dingtalk_stream import DingTalkStreamClient
from django.db import close_old_connections
from websockets.asyncio.client import connect as websocket_connect

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
    from contextlib import AbstractAsyncContextManager

    from dingtalk_stream import Credential

logger = logging.getLogger(__name__)

STREAM_OPEN_CONNECT_TIMEOUT_SECONDS: Final = 5.0
STREAM_OPEN_READ_TIMEOUT_SECONDS: Final = 15.0
STREAM_SESSION_POLL_SECONDS: Final = 1.0
DINGTALK_STREAM_SDK_VERSION: Final = package_version("dingtalk-stream")

STREAM_OPEN_FAILED_MESSAGE: Final = "钉钉 Stream 打开连接失败。"
STREAM_INVALID_MESSAGE_MESSAGE: Final = "钉钉 Stream 收到非文本消息, 无法解析。"
STREAM_START_FOREVER_FORBIDDEN_MESSAGE: Final = (
    "钉钉 Stream 禁止使用 SDK 的 start_forever 固定重连, 必须走监督循环。"
)
STREAM_CLIENT_TYPE_MESSAGE: Final = (
    "钉钉 Stream 会话必须使用 SingleSessionDingTalkStreamClient, "
    "禁止 SDK 默认 start() 内循环。"
)
STREAM_PAUSED_CLOSE_MESSAGE: Final = "钉钉 Stream 已按用量策略暂停, 正在关闭当前连接。"
STREAM_PREDICATE_FAILED_MESSAGE: Final = "钉钉 Stream 会话内策略检查失败, 保持连接并在下一轮重试。"
STREAM_SESSION_TASK_FAILED_MESSAGE: Final = "钉钉 Stream 会话任务异常结束。"
STREAM_PREDICATE_WARNING_INTERVAL_SECONDS: Final = 60.0
_STREAM_ENDED: Final = object()


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


class _OpenHttpResponse(Protocol):
    status_code: int

    def json(self) -> object: ...


@dataclass(frozen=True, slots=True)
class _OpenConnectionHttp:
    url: str
    headers: dict[str, str]
    body: bytes


def _stream_always_run() -> bool:
    return True


def _stream_never_stop() -> bool:
    return False


def _skip_record_stream_open() -> None:
    return None


@dataclass(slots=True)
class _WarningRateLimiter:
    interval_seconds: float
    clock: Callable[[], float] = time.monotonic
    next_allowed_at: float = 0.0

    def warning(self, message: str, error: BaseException | None = None) -> None:
        now = self.clock()
        if now < self.next_allowed_at:
            return
        self.next_allowed_at = now + self.interval_seconds
        logger.warning(message, exc_info=error)


@dataclass(frozen=True, slots=True)
class _SessionExitWatch:
    should_run: Callable[[], bool]
    should_stop: Callable[[], bool]
    interval_seconds: float
    exit_requested: asyncio.Event
    warnings: _WarningRateLimiter


@dataclass(frozen=True, slots=True)
class _IncomingWait:
    messages: AsyncIterator[object]
    exit_wait: asyncio.Task[bool]
    exit_requested: asyncio.Event


@final
class SingleSessionDingTalkStreamClient(DingTalkStreamClient):
    """一次 start() 只打开一次连接并消费一个 WebSocket 会话, 不在 SDK 内重试。"""

    stream_should_run: Callable[[], bool]
    record_stream_open: Callable[[], None]
    session_should_stop: Callable[[], bool]
    pause_poll_seconds: float
    last_websocket_seconds: float
    clock: Callable[[], float]

    @override
    def __init__(
        self,
        credential: Credential,
        logger: logging.Logger | None = None,
    ) -> None:
        super().__init__(credential, logger)
        # 可注入 callable 必须写在实例上: 类属性上的裸函数经 self 访问会变成 bound method。
        self.stream_should_run = _stream_always_run
        self.record_stream_open = _skip_record_stream_open
        self.session_should_stop = _stream_never_stop
        self.pause_poll_seconds = STREAM_SESSION_POLL_SECONDS
        self.last_websocket_seconds = 0.0
        self.clock = time.monotonic

    @override
    def start_forever(self) -> None:
        raise StreamStartForeverForbiddenError

    @override
    def open_connection(self) -> dict[str, object]:
        try:
            return _payload_from_open_response(_post_stream_open(self._open_connection_http()))
        except StreamOpenConnectionError:
            raise
        except Exception as error:
            raise StreamOpenConnectionError from error

    def _open_connection_http(self) -> _OpenConnectionHttp:
        return _OpenConnectionHttp(
            url=DingTalkStreamClient.OPEN_CONNECTION_API,
            headers=_open_connection_headers(),
            body=self._open_connection_body(),
        )

    def _open_connection_body(self) -> bytes:
        payload = {
            "clientId": self.credential.client_id,
            "clientSecret": self.credential.client_secret,
            "subscriptions": self._open_connection_subscriptions(),
            "ua": f"dingtalk-sdk-python/v{DINGTALK_STREAM_SDK_VERSION}-union",
            "localIp": self.get_host_ip(),
        }
        return dumps(payload).encode("utf-8")

    def _open_connection_subscriptions(self) -> list[dict[str, str]]:
        topics: list[dict[str, str]] = []
        if self._is_event_required:
            topics.append({"type": "EVENT", "topic": "*"})
        topics.extend({"type": "CALLBACK", "topic": topic} for topic in self.callback_handler_map)
        return topics

    @override
    async def start(self) -> None:
        self.last_websocket_seconds = 0.0
        # 策略查询缓存未命中会走同步 ORM, 记账会写缓存, 都只能经 to_thread 离开事件循环线程。
        if not await _session_may_open(self):
            return
        await _off_loop(self.record_stream_open)
        self.pre_start()
        connection = await asyncio.to_thread(self.open_connection)
        if not await _session_may_open(self):
            return
        await _consume_websocket(self, _websocket_uri(connection))


def run_one_stream_session(client: DingTalkStreamClient) -> None:
    if not isinstance(client, SingleSessionDingTalkStreamClient):
        raise StreamClientTypeError
    asyncio.run(client.start())


def _open_connection_headers() -> dict[str, str]:
    user_agent = (
        f"DingTalkStream/1.0 SDK/{DINGTALK_STREAM_SDK_VERSION} "
        f"Python/{platform.python_version()} "
        "(+https://github.com/open-dingtalk/dingtalk-stream-sdk-python)"
    )
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": user_agent,
    }


def _post_stream_open(request: _OpenConnectionHttp) -> _OpenHttpResponse:
    return cast(
        "_OpenHttpResponse",
        requests.post(
            request.url,
            headers=request.headers,
            data=request.body,
            timeout=(STREAM_OPEN_CONNECT_TIMEOUT_SECONDS, STREAM_OPEN_READ_TIMEOUT_SECONDS),
        ),
    )


def _payload_from_open_response(response: _OpenHttpResponse) -> dict[str, object]:
    if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
        raise StreamOpenConnectionError
    try:
        parsed: object = response.json()
    except (TypeError, ValueError) as error:
        raise StreamOpenConnectionError from error
    return _validated_open_connection_payload(parsed)


def _validated_open_connection_payload(parsed: object) -> dict[str, object]:
    if not isinstance(parsed, dict):
        raise StreamOpenConnectionError
    payload = cast("dict[str, object]", parsed)
    endpoint = payload.get("endpoint")
    ticket = payload.get("ticket")
    if not isinstance(endpoint, str) or not endpoint:
        raise StreamOpenConnectionError
    if not isinstance(ticket, str) or not ticket:
        raise StreamOpenConnectionError
    return payload


def _websocket_uri(connection: object) -> str:
    payload = _validated_open_connection_payload(connection)
    endpoint = cast("str", payload["endpoint"])
    ticket = cast("str", payload["ticket"])
    return f"{endpoint}?ticket={quote_plus(ticket)}"


async def _consume_websocket(client: SingleSessionDingTalkStreamClient, uri: str) -> None:
    # 健康时长从 WebSocket 连上起算; 打开 HTTP 或握手失败不得清零退避。
    connected_at: float | None = None
    try:
        async with _websocket_session(uri) as websocket:
            connected_at = client.clock()
            client.websocket = websocket
            await _run_connected_session(client, websocket)
    finally:
        _record_websocket_seconds(client, connected_at)


async def _run_connected_session(
    client: SingleSessionDingTalkStreamClient,
    websocket: object,
) -> None:
    tasks: set[asyncio.Task[None]] = set()
    watch = _new_exit_watch(client)
    try:
        _start_session_tasks(client, websocket, tasks, watch)
        await _drain_websocket_messages(client, websocket, tasks, watch)
    finally:
        await _release_connected_session(client, websocket, tasks)


def _new_exit_watch(client: SingleSessionDingTalkStreamClient) -> _SessionExitWatch:
    return _SessionExitWatch(
        should_run=client.stream_should_run,
        should_stop=client.session_should_stop,
        interval_seconds=client.pause_poll_seconds,
        exit_requested=asyncio.Event(),
        warnings=_WarningRateLimiter(STREAM_PREDICATE_WARNING_INTERVAL_SECONDS),
    )


def _start_session_tasks(
    client: SingleSessionDingTalkStreamClient,
    websocket: object,
    tasks: set[asyncio.Task[None]],
    watch: _SessionExitWatch,
) -> None:
    _track_task(tasks, cast("Coroutine[object, object, None]", client.keepalive(websocket)))
    _track_task(tasks, cast("Coroutine[object, object, None]", _watch_stream_session_exit(watch)))
    # 停止轮询与监视任务分开: 监视任务退出后, 停止事件仍能结束会话。
    _track_task(tasks, cast("Coroutine[object, object, None]", _poll_until_stop(watch)))


async def _drain_websocket_messages(
    client: SingleSessionDingTalkStreamClient,
    websocket: object,
    tasks: set[asyncio.Task[None]],
    watch: _SessionExitWatch,
) -> None:
    incoming = _IncomingWait(
        messages=_iter_websocket_messages(websocket).__aiter__(),
        exit_wait=asyncio.create_task(watch.exit_requested.wait()),
        exit_requested=watch.exit_requested,
    )
    try:
        await _pump_stream_messages(client, tasks, incoming)
    finally:
        await _cancel_task(incoming.exit_wait)


async def _pump_stream_messages(
    client: SingleSessionDingTalkStreamClient,
    tasks: set[asyncio.Task[None]],
    incoming: _IncomingWait,
) -> None:
    while not incoming.exit_requested.is_set():
        arrived, raw_message = await _next_stream_message(incoming)
        if not arrived:
            return
        _schedule_stream_message(client, tasks, raw_message)


async def _next_stream_message(incoming: _IncomingWait) -> tuple[bool, object]:
    reader = asyncio.create_task(_read_next_message(incoming.messages))
    done = (
        await asyncio.wait(
            {reader, incoming.exit_wait},
            return_when=asyncio.FIRST_COMPLETED,
        )
    )[0]
    if reader not in done:
        await _cancel_task(reader)
        return False, None
    message = reader.result()
    if message is _STREAM_ENDED:
        return False, None
    return True, message


async def _read_next_message(messages: AsyncIterator[object]) -> object:
    try:
        return await anext(messages)
    except StopAsyncIteration:
        return _STREAM_ENDED


def _schedule_stream_message(
    client: SingleSessionDingTalkStreamClient,
    tasks: set[asyncio.Task[None]],
    raw_message: object,
) -> None:
    _track_task(
        tasks,
        cast(
            "Coroutine[object, object, None]",
            client.background_task(_decode_stream_message(raw_message)),
        ),
    )


async def _release_connected_session(
    client: SingleSessionDingTalkStreamClient,
    websocket: object,
    tasks: set[asyncio.Task[None]],
) -> None:
    try:
        await _shutdown_session_tasks(tasks)
    finally:
        await _close_stream_websocket(websocket)
        client.websocket = None


def _record_websocket_seconds(
    client: SingleSessionDingTalkStreamClient,
    connected_at: float | None,
) -> None:
    if connected_at is None:
        return
    client.last_websocket_seconds = client.clock() - connected_at


async def _shutdown_session_tasks(tasks: set[asyncio.Task[None]]) -> None:
    pending = [task for task in tasks if not task.done()]
    for task in pending:
        _ = task.cancel()
    if pending:
        _ = await asyncio.gather(*pending, return_exceptions=True)


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

    def _done(done: asyncio.Task[None]) -> None:
        _on_session_task_done(tasks, done)

    task.add_done_callback(_done)


def _on_session_task_done(tasks: set[asyncio.Task[None]], task: asyncio.Task[None]) -> None:
    tasks.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.warning(STREAM_SESSION_TASK_FAILED_MESSAGE, exc_info=error)


async def _session_may_open(client: SingleSessionDingTalkStreamClient) -> bool:
    if client.session_should_stop():
        return False
    allowed = await _off_loop(client.stream_should_run)
    return allowed and not client.session_should_stop()


async def _watch_stream_session_exit(watch: _SessionExitWatch) -> None:
    while not watch.exit_requested.is_set():
        if _request_stop_if_needed(watch):
            return
        if not await _stream_should_keep_running(watch):
            logger.warning(STREAM_PAUSED_CLOSE_MESSAGE)
            watch.exit_requested.set()
            return
        await asyncio.sleep(watch.interval_seconds)


async def _poll_until_stop(watch: _SessionExitWatch) -> None:
    # 停止判断留在事件循环线程: 线程池卡住时 SIGTERM 仍能结束会话并在 finally 里关连接。
    while not watch.exit_requested.is_set():
        if _request_stop_if_needed(watch):
            return
        await asyncio.sleep(watch.interval_seconds)


def _request_stop_if_needed(watch: _SessionExitWatch) -> bool:
    if not _predicate_is_true(watch.should_stop, watch.warnings):
        return False
    watch.exit_requested.set()
    return True


def _predicate_is_true(predicate: Callable[[], bool], warnings: _WarningRateLimiter) -> bool:
    try:
        return predicate()
    except Exception as error:  # noqa: BLE001 - 谓词任意异常都不得杀死会话监视任务, 否则 SIGTERM/暂停失效.
        warnings.warning(STREAM_PREDICATE_FAILED_MESSAGE, error)
        return False


async def _stream_should_keep_running(watch: _SessionExitWatch) -> bool:
    try:
        return await _off_loop(watch.should_run)
    except Exception as error:  # noqa: BLE001 - 同上, 监视任务必须存活, 异常按"继续运行"处理.
        watch.warnings.warning(STREAM_PREDICATE_FAILED_MESSAGE, error)
        return True


async def _cancel_task[T](task: asyncio.Task[T]) -> None:
    if not task.done():
        _ = task.cancel()
        _ = await asyncio.gather(task, return_exceptions=True)
    if not task.cancelled():
        _ = task.exception()


async def _close_stream_websocket(websocket: object) -> None:
    close = getattr(websocket, "close", None)
    if not callable(close):
        return
    result = close()
    if inspect.isawaitable(result):
        _ = await cast("Awaitable[object]", result)


async def _off_loop[R](func: Callable[[], R]) -> R:
    # 策略查询可能回落到同步 ORM, Django 禁止在事件循环线程访问 ORM, 故放到线程池执行。
    return await asyncio.to_thread(_with_fresh_db_connection, func)


def _with_fresh_db_connection[R](func: Callable[[], R]) -> R:
    # 常驻 Stream 进程没有请求/任务生命周期替我们回收连接; 线程池线程里的连接在
    # PostgreSQL 重启或超过 CONN_MAX_AGE 后会失效, 每次调用前后按 Django 规则回收。
    close_old_connections()
    try:
        return func()
    finally:
        close_old_connections()
