from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import pytest
from dingtalk_stream import Credential, DingTalkStreamClient, EventHandler
from requests.exceptions import Timeout

from easyauth.integrations.dingtalk import stream_session as session_module
from easyauth.integrations.dingtalk.errors import DingTalkCallBudgetExceededError
from easyauth.integrations.dingtalk.stream_runner import (
    StreamSupervisorHooks,
    bind_stream_session,
    run_supervised_stream,
)
from easyauth.integrations.dingtalk.stream_session import (
    STREAM_OPEN_CONNECT_TIMEOUT_SECONDS,
    STREAM_OPEN_READ_TIMEOUT_SECONDS,
    SingleSessionDingTalkStreamClient,
    StreamClientTypeError,
    StreamOpenConnectionError,
    StreamStartForeverForbiddenError,
    run_one_stream_session,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Self


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


def test_start_skips_open_when_paused(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    client.stream_should_run = lambda: False
    opened: list[str] = []
    monkeypatch.setattr(client, "open_connection", lambda: opened.append("open"))
    asyncio.run(client.start())
    assert opened == []


def test_start_records_open_before_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    calls: list[str] = []

    def refuse() -> None:
        calls.append("record")
        raise DingTalkCallBudgetExceededError

    monkeypatch.setattr(client, "open_connection", lambda: calls.append("open"))
    client.record_stream_open = refuse
    with pytest.raises(DingTalkCallBudgetExceededError):
        asyncio.run(client.start())
    assert calls == ["record"]


def test_pause_watch_closes_websocket(monkeypatch: pytest.MonkeyPatch) -> None:
    paused = threading.Event()
    websocket = _StoppableWebSocket(paused)
    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    client.stream_should_run = lambda: not paused.is_set()
    client.pause_poll_seconds = 0.01
    monkeypatch.setattr(
        client,
        "open_connection",
        lambda: {"endpoint": "wss://example.test", "ticket": "t"},
    )
    monkeypatch.setattr(session_module, "_websocket_session", lambda _uri: websocket)
    asyncio.run(client.start())
    assert websocket.close_calls == 1


def test_open_connection_posts_with_connect_and_read_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    monkeypatch.setattr(client, "get_host_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(session_module.requests, "post", _capture_post(captured))
    payload = client.open_connection()
    assert captured["timeout"] == (
        STREAM_OPEN_CONNECT_TIMEOUT_SECONDS,
        STREAM_OPEN_READ_TIMEOUT_SECONDS,
    )
    assert captured["url"] == DingTalkStreamClient.OPEN_CONNECTION_API
    body = captured["data"]
    assert isinstance(body, bytes)
    assert b"app-key" in body
    assert payload == {"endpoint": "wss://example.test", "ticket": "t"}


def test_open_connection_timeout_is_failed_open(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    monkeypatch.setattr(client, "get_host_ip", lambda: "127.0.0.1")

    def hanging_post(*args: object, **kwargs: object) -> object:
        del args
        timeout = kwargs.get("timeout")
        if timeout is None:
            message = "open_connection must pass timeout"
            raise AssertionError(message)
        raise Timeout

    monkeypatch.setattr(session_module.requests, "post", hanging_post)
    with pytest.raises(StreamOpenConnectionError, match="打开连接失败"):
        client.open_connection()


def test_open_connection_rejects_non_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    monkeypatch.setattr(client, "get_host_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(
        session_module.requests,
        "post",
        _fixed_post(500, {"endpoint": "wss://x", "ticket": "t"}),
    )
    with pytest.raises(StreamOpenConnectionError, match="打开连接失败"):
        client.open_connection()


def test_open_connection_rejects_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    monkeypatch.setattr(client, "get_host_ip", lambda: "127.0.0.1")

    class _Resp:
        status_code = 200

        def json(self) -> object:
            message = "not json"
            raise ValueError(message)

    def fake_post(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return _Resp()

    monkeypatch.setattr(session_module.requests, "post", fake_post)
    with pytest.raises(StreamOpenConnectionError, match="打开连接失败"):
        client.open_connection()


def test_teardown_cancels_keepalive_and_background_before_socket_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    websocket = _MessageWebSocket(['{"type":"x"}'], order)
    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    monkeypatch.setattr(
        client,
        "open_connection",
        lambda: {"endpoint": "wss://example.test", "ticket": "t"},
    )
    monkeypatch.setattr(session_module, "_websocket_session", lambda _uri: websocket)
    monkeypatch.setattr(client, "keepalive", _hanging_named(order, "keepalive"))
    monkeypatch.setattr(client, "background_task", _hanging_named(order, "background"))
    asyncio.run(client.start())
    assert order[-1] == "ws-exit"
    assert set(order[:-1]) == {"keepalive", "background"}


def test_teardown_does_not_ack_on_closed_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    websocket = _MessageWebSocket(['{"type":"x"}'], [])
    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    monkeypatch.setattr(
        client,
        "open_connection",
        lambda: {"endpoint": "wss://example.test", "ticket": "t"},
    )
    monkeypatch.setattr(session_module, "_websocket_session", lambda _uri: websocket)

    async def delayed_ack(_json_message: object) -> None:
        await asyncio.sleep(0.05)
        await websocket.send("ack")

    monkeypatch.setattr(client, "background_task", delayed_ack)
    monkeypatch.setattr(client, "keepalive", _hanging_named([], "keepalive"))
    asyncio.run(client.start())
    assert websocket.sends == []
    assert websocket.closed is True


def _capture_post(captured: dict[str, object]) -> Callable[..., object]:
    def fake_post(url: str, *, headers: object, data: object, timeout: object) -> object:
        captured["url"] = url
        captured["headers"] = headers
        captured["data"] = data
        captured["timeout"] = timeout
        return _JsonResponse(200, {"endpoint": "wss://example.test", "ticket": "t"})

    return fake_post


def _fixed_post(status: int, payload: dict[str, object]) -> Callable[..., object]:
    def fake_post(*args: object, **kwargs: object) -> object:
        del args, kwargs
        return _JsonResponse(status, payload)

    return fake_post


def _hanging_named(order: list[str], name: str) -> Callable[..., object]:
    async def hanging(*args: object, **kwargs: object) -> None:
        del args, kwargs
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            order.append(name)
            raise

    return hanging


class _JsonResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload


class _MessageWebSocket:
    def __init__(self, messages: list[str], order: list[str]) -> None:
        self._messages = list(messages)
        self._order = order
        self.closed = False
        self.sends: list[str] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args
        self.closed = True
        self._order.append("ws-exit")

    def __aiter__(self) -> _MessageWebSocket:
        return self

    async def __anext__(self) -> str:
        # 真实 websocket 每次取消息都会让出事件循环; 这里同样让出, 已建的任务才来得及启动。
        await asyncio.sleep(0)
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def send(self, data: str) -> None:
        self.sends.append(data)
        if self.closed:
            message = "ack send on closed socket"
            raise OSError(message)

    async def close(self) -> None:
        self.closed = True


def test_open_connection_body_includes_event_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    client.register_all_event_handler(EventHandler())
    monkeypatch.setattr(client, "get_host_ip", lambda: "10.0.0.1")
    monkeypatch.setattr(session_module.requests, "post", _capture_post(captured))
    _ = client.open_connection()
    body = captured["data"]
    assert isinstance(body, bytes)
    assert b'"EVENT"' in body
    assert b"10.0.0.1" in body


OPEN_HANG_WALL_SECONDS = 70.0
SHORT_SESSION_SECONDS = 1.0


def test_websocket_connected_beyond_healthy_window_resets_streak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps, now = _run_connected_durations(
        monkeypatch,
        [SHORT_SESSION_SECONDS, SHORT_SESSION_SECONDS, 61.0],
    )
    assert sleeps == [5.0, 10.0, 5.0]
    assert now["t"] == SHORT_SESSION_SECONDS * 2 + 61.0


def test_websocket_connect_failure_does_not_reset_streak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = {"t": 0.0}
    sleeps: list[float] = []

    class _FailingConnect:
        async def __aenter__(self) -> Self:
            now["t"] += OPEN_HANG_WALL_SECONDS
            message = "websocket connect failed"
            raise OSError(message)

        async def __aexit__(self, *args: object) -> None:
            del args

    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    client.clock = lambda: now["t"]
    monkeypatch.setattr(
        client,
        "open_connection",
        lambda: {"endpoint": "wss://example.test", "ticket": "t"},
    )
    monkeypatch.setattr(session_module, "_websocket_session", lambda _uri: _FailingConnect())
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


def test_stop_during_connected_session_exits_without_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stop = threading.Event()
    sleeps: list[float] = []
    websocket = _StoppableWebSocket(stop)
    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    client.pause_poll_seconds = 0.01
    monkeypatch.setattr(
        client,
        "open_connection",
        lambda: {"endpoint": "wss://example.test", "ticket": "t"},
    )
    monkeypatch.setattr(session_module, "_websocket_session", lambda _uri: websocket)
    run_supervised_stream(
        bind_stream_session(client, should_stop=stop.is_set),
        StreamSupervisorHooks(
            should_stop=stop.is_set,
            sleep=sleeps.append,
            unit_interval=lambda: 0.0,
        ),
    )
    assert stop.is_set()
    assert sleeps == []
    assert websocket.close_calls == 1


def _run_connected_durations(
    monkeypatch: pytest.MonkeyPatch,
    durations: list[float],
) -> tuple[list[float], dict[str, float]]:
    now = {"t": 0.0}
    sleeps: list[float] = []
    remaining = list(durations)
    client = SingleSessionDingTalkStreamClient(Credential("app-key", "app-secret"))
    client.clock = lambda: now["t"]
    monkeypatch.setattr(
        client,
        "open_connection",
        lambda: {"endpoint": "wss://example.test", "ticket": "t"},
    )
    monkeypatch.setattr(
        session_module,
        "_websocket_session",
        lambda _uri: _TimedWebSocket(now, remaining),
    )
    run_supervised_stream(
        bind_stream_session(client),
        StreamSupervisorHooks(
            should_stop=lambda: len(sleeps) >= len(durations),
            sleep=sleeps.append,
            clock=lambda: now["t"],
            unit_interval=lambda: 0.0,
        ),
    )
    return sleeps, now


class _TimedWebSocket:
    def __init__(self, now: dict[str, float], remaining: list[float]) -> None:
        self._now = now
        self._remaining = remaining
        self._consumed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    def __aiter__(self) -> _TimedWebSocket:
        return self

    async def __anext__(self) -> str:
        if self._consumed:
            raise StopAsyncIteration
        self._consumed = True
        self._now["t"] += self._remaining.pop(0)
        raise StopAsyncIteration


class _StoppableWebSocket:
    def __init__(self, stop: threading.Event) -> None:
        self._stop = stop
        self._closed: asyncio.Event | None = None
        self.close_calls = 0

    async def __aenter__(self) -> Self:
        self._closed = asyncio.Event()
        self._stop.set()
        return self

    async def __aexit__(self, *args: object) -> None:
        del args
        if self._closed is not None:
            self._closed.set()

    def __aiter__(self) -> _StoppableWebSocket:
        return self

    async def __anext__(self) -> str:
        closed = self._closed
        if closed is None:
            message = "websocket was not entered"
            raise AssertionError(message)
        try:
            await asyncio.wait_for(closed.wait(), timeout=2.0)
        except TimeoutError:
            message = "connected session did not close after stop"
            raise AssertionError(message) from None
        raise StopAsyncIteration

    async def close(self) -> None:
        self.close_calls += 1
        if self._closed is not None:
            self._closed.set()
