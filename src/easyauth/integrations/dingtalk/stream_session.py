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

    def _session_may_open(self) -> bool:
        return not self.session_should_stop() and self.stream_should_run()

    @override
    async def start(self) -> None:
        self.last_websocket_seconds = 0.0
        if not self._session_may_open():
            return
        self.record_stream_open()
        self.pre_start()
        connection = await asyncio.to_thread(self.open_connection)
        if not self._session_may_open():
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
    tasks: set[asyncio.Task[None]] = set()
    connected_at: float | None = None
    try:
        async with _websocket_session(uri) as websocket:
            connected_at = client.clock()
            client.websocket = websocket
            try:
                _start_session_tasks(client, websocket, tasks)
                await _drain_websocket_messages(client, websocket, tasks)
            finally:
                await _shutdown_session_tasks(tasks)
                client.websocket = None
    finally:
        _record_websocket_seconds(client, connected_at)


def _start_session_tasks(
    client: SingleSessionDingTalkStreamClient,
    websocket: object,
    tasks: set[asyncio.Task[None]],
) -> None:
    _track_task(tasks, cast("Coroutine[object, object, None]", client.keepalive(websocket)))
    _track_task(
        tasks,
        _watch_stream_session_exit(
            websocket,
            client.stream_should_run,
            client.session_should_stop,
            client.pause_poll_seconds,
        ),
    )


async def _drain_websocket_messages(
    client: SingleSessionDingTalkStreamClient,
    websocket: object,
    tasks: set[asyncio.Task[None]],
) -> None:
    async for raw_message in _iter_websocket_messages(websocket):
        _track_task(
            tasks,
            cast(
                "Coroutine[object, object, None]",
                client.background_task(_decode_stream_message(raw_message)),
            ),
        )


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
    task.add_done_callback(tasks.discard)


async def _watch_stream_session_exit(
    websocket: object,
    should_run: Callable[[], bool],
    should_stop: Callable[[], bool],
    interval_seconds: float,
) -> None:
    while True:
        if should_stop() or not should_run():
            if not should_stop() and not should_run():
                logger.warning(STREAM_PAUSED_CLOSE_MESSAGE)
            await _close_stream_websocket(websocket)
            return
        await asyncio.sleep(interval_seconds)


async def _close_stream_websocket(websocket: object) -> None:
    close = getattr(websocket, "close", None)
    if not callable(close):
        return
    result = close()
    if inspect.isawaitable(result):
        _ = await cast("Awaitable[object]", result)
