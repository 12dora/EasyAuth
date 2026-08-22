from __future__ import annotations

import json
import threading
from http import HTTPStatus
from typing import TYPE_CHECKING, Final
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import pytest
from celery.signals import worker_ready, worker_shutdown, worker_shutting_down

from easyauth.config.worker_health import (
    CHECK_IN_PROGRESS_MESSAGE,
    CHECK_TIMEOUT_MESSAGE,
    HEALTH_PATH,
    HEALTH_PORT_ENV,
    PING_TIMEOUT_SECONDS,
    PONG_PAYLOAD,
    SHUTTING_DOWN_MESSAGE,
    THREAD_NAME,
    WORKER_PING_FAILED_MESSAGE,
    bound_health_port,
    check_worker_ping,
    connect_worker_health_signals,
    health_response,
    start_worker_health_server,
    stop_worker_health_server,
    worker_health_port,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from http.server import ThreadingHTTPServer

WORKER_HOSTNAME: Final = "webhooks@testhost"
URLOPEN_TIMEOUT_SECONDS: Final = 2.0
BLOCKING_CHECKER_WAIT_SECONDS: Final = 30.0
HTTP_OK: Final = int(HTTPStatus.OK)
HTTP_NOT_FOUND: Final = int(HTTPStatus.NOT_FOUND)
HTTP_UNAVAILABLE: Final = int(HTTPStatus.SERVICE_UNAVAILABLE)


class _FakeControl:
    def __init__(
        self,
        *,
        replies: object | None = None,
        error: BaseException | None = None,
    ) -> None:
        default = [{WORKER_HOSTNAME: dict(PONG_PAYLOAD)}]
        self.replies: object = default if replies is None else replies
        self.error = error
        self.calls: list[tuple[list[str], float]] = []

    def ping(self, destination: list[str], timeout: float) -> object:
        self.calls.append((list(destination), timeout))
        if self.error is not None:
            raise self.error
        return self.replies


class _FakeApp:
    def __init__(self, control: _FakeControl | None = None) -> None:
        self.control = control if control is not None else _FakeControl()


class _FakeWorker:
    def __init__(self, app: _FakeApp, hostname: str = WORKER_HOSTNAME) -> None:
        self.app = app
        self.hostname = hostname


@pytest.fixture(autouse=True)
def _stop_health_server() -> Iterator[None]:
    stop_worker_health_server()
    yield
    stop_worker_health_server()


def test_health_handler_returns_200_when_checker_passes() -> None:
    server = start_worker_health_server(
        _FakeApp(),
        port=0,
        worker_hostname=WORKER_HOSTNAME,
        checker=lambda: True,
    )
    status, payload = _get(f"{_base_url(server)}/health")
    assert status == HTTP_OK
    assert payload == {"status": "ok", "worker": WORKER_HOSTNAME}


def test_health_handler_returns_503_when_checker_fails() -> None:
    server = start_worker_health_server(
        _FakeApp(),
        port=0,
        worker_hostname=WORKER_HOSTNAME,
        checker=lambda: False,
    )
    status, payload = _get(f"{_base_url(server)}/health")
    assert status == HTTP_UNAVAILABLE
    assert payload == {"status": "error", "error": WORKER_PING_FAILED_MESSAGE}


def test_health_handler_returns_404_on_other_paths() -> None:
    server = start_worker_health_server(
        _FakeApp(),
        port=0,
        worker_hostname=WORKER_HOSTNAME,
        checker=lambda: True,
    )
    status, payload = _get(f"{_base_url(server)}/ready")
    assert status == HTTP_NOT_FOUND
    assert payload == {"error": "not found"}


def test_start_worker_health_server_twice_is_idempotent() -> None:
    app = _FakeApp()
    first = start_worker_health_server(app, port=0, worker_hostname=WORKER_HOSTNAME)
    second = start_worker_health_server(app, port=0, worker_hostname=WORKER_HOSTNAME)
    assert first is second
    named = [thread for thread in threading.enumerate() if thread.name == THREAD_NAME]
    assert named == [_require_thread()]
    status, payload = _get(f"{_base_url(first)}/health")
    assert status == HTTP_OK
    assert payload == {"status": "ok", "worker": WORKER_HOSTNAME}
    assert app.control.calls == [([WORKER_HOSTNAME], PING_TIMEOUT_SECONDS)]


def test_stop_worker_health_server_closes_socket() -> None:
    server = start_worker_health_server(
        _FakeApp(),
        port=0,
        worker_hostname=WORKER_HOSTNAME,
    )
    url = f"{_base_url(server)}/health"
    status, _payload = _get(url)
    assert status == HTTP_OK
    stop_worker_health_server()
    with pytest.raises((ConnectionError, URLError)):
        _ = urlopen(url, timeout=URLOPEN_TIMEOUT_SECONDS)  # noqa: S310 - 本机 ephemeral 健康端口.


def test_check_worker_ping_returns_true_when_reply_is_pong() -> None:
    control = _FakeControl(replies=[{WORKER_HOSTNAME: dict(PONG_PAYLOAD)}])
    assert check_worker_ping(_FakeApp(control), WORKER_HOSTNAME) is True
    assert control.calls == [([WORKER_HOSTNAME], PING_TIMEOUT_SECONDS)]


def test_check_worker_ping_returns_false_when_reply_is_empty() -> None:
    control = _FakeControl(replies=[])
    assert check_worker_ping(_FakeApp(control), WORKER_HOSTNAME) is False
    assert control.calls == [([WORKER_HOSTNAME], PING_TIMEOUT_SECONDS)]


def test_check_worker_ping_returns_false_when_ping_raises() -> None:
    control = _FakeControl(error=ConnectionError("broker down"))
    assert check_worker_ping(_FakeApp(control), WORKER_HOSTNAME) is False
    assert control.calls == [([WORKER_HOSTNAME], PING_TIMEOUT_SECONDS)]


def test_health_response_times_out_when_checker_blocks() -> None:
    release = threading.Event()
    finished = threading.Event()

    def slow() -> bool:
        try:
            _ = release.wait(timeout=BLOCKING_CHECKER_WAIT_SECONDS)
            return True
        finally:
            finished.set()

    try:
        status, payload = health_response(
            HEALTH_PATH,
            checker=slow,
            worker_hostname=WORKER_HOSTNAME,
        )
        assert status == HTTPStatus.SERVICE_UNAVAILABLE
        assert payload == {"status": "error", "error": CHECK_TIMEOUT_MESSAGE}
    finally:
        release.set()
        assert finished.wait(timeout=URLOPEN_TIMEOUT_SECONDS)


def test_health_response_returns_503_when_check_in_progress() -> None:
    started = threading.Event()
    release = threading.Event()

    def slow() -> bool:
        started.set()
        _ = release.wait(timeout=BLOCKING_CHECKER_WAIT_SECONDS)
        return True

    first_result: list[tuple[HTTPStatus, dict[str, str]]] = []

    def first_check() -> None:
        first_result.append(
            health_response(
                HEALTH_PATH,
                checker=slow,
                worker_hostname=WORKER_HOSTNAME,
            )
        )

    first = threading.Thread(target=first_check)
    first.start()
    assert started.wait(timeout=URLOPEN_TIMEOUT_SECONDS)
    status, payload = health_response(
        HEALTH_PATH,
        checker=lambda: True,
        worker_hostname=WORKER_HOSTNAME,
    )
    assert status == HTTPStatus.SERVICE_UNAVAILABLE
    assert payload == {"status": "error", "error": CHECK_IN_PROGRESS_MESSAGE}
    release.set()
    first.join(timeout=URLOPEN_TIMEOUT_SECONDS)
    assert first_result == [(HTTPStatus.OK, {"status": "ok", "worker": WORKER_HOSTNAME})]


def test_health_returns_503_when_shutting_down() -> None:
    connect_worker_health_signals()
    server = start_worker_health_server(
        _FakeApp(),
        port=0,
        worker_hostname=WORKER_HOSTNAME,
        checker=_fail_if_called,
    )
    url = f"{_base_url(server)}/health"
    _ = worker_shutting_down.send(
        sender=WORKER_HOSTNAME,
        sig="TERM",
        how="Warm",
        exitcode=0,
    )
    status, payload = _get(url)
    assert status == HTTP_UNAVAILABLE
    assert payload == {"status": "error", "error": SHUTTING_DOWN_MESSAGE}
    _ = worker_shutdown.send(sender=WORKER_HOSTNAME)
    with pytest.raises((ConnectionError, URLError)):
        _ = urlopen(url, timeout=URLOPEN_TIMEOUT_SECONDS)  # noqa: S310 - 本机 ephemeral 健康端口.


def test_connect_signals_is_idempotent() -> None:
    connect_worker_health_signals()
    ready_count = len(worker_ready.receivers)
    shutdown_count = len(worker_shutdown.receivers)
    shutting_down_count = len(worker_shutting_down.receivers)
    connect_worker_health_signals()
    assert len(worker_ready.receivers) == ready_count
    assert len(worker_shutdown.receivers) == shutdown_count
    assert len(worker_shutting_down.receivers) == shutting_down_count


def test_worker_ready_signal_starts_single_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HEALTH_PORT_ENV, "0")
    connect_worker_health_signals()
    control = _FakeControl()
    worker = _FakeWorker(_FakeApp(control))
    _ = worker_ready.send(sender=worker)
    _ = worker_ready.send(sender=worker)
    named = [thread for thread in threading.enumerate() if thread.name == THREAD_NAME]
    assert len(named) == 1
    server = start_worker_health_server(worker.app, port=0)
    status, payload = _get(f"{_base_url(server)}/health")
    assert status == HTTP_OK
    assert payload == {"status": "ok", "worker": WORKER_HOSTNAME}
    assert control.calls == [([WORKER_HOSTNAME], PING_TIMEOUT_SECONDS)]


def test_worker_health_port_env_empty_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HEALTH_PORT_ENV, "")
    with pytest.raises(ValueError, match=HEALTH_PORT_ENV):
        _ = worker_health_port()


def test_worker_health_port_rejects_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HEALTH_PORT_ENV, "65536")
    with pytest.raises(ValueError, match=HEALTH_PORT_ENV):
        _ = worker_health_port()


def _base_url(server: ThreadingHTTPServer) -> str:
    return f"http://127.0.0.1:{bound_health_port(server)}"


def _get(url: str) -> tuple[int, dict[str, str]]:
    try:
        with urlopen(url, timeout=URLOPEN_TIMEOUT_SECONDS) as response:  # noqa: S310 - 本机 ephemeral 健康端口.
            return response.status, _read_object(response.read())
    except HTTPError as error:
        return error.code, _read_object(error.read())


def _read_object(raw: bytes) -> dict[str, str]:
    payload = json.loads(raw.decode("utf-8"))
    assert isinstance(payload, dict)
    return {str(key): str(value) for key, value in payload.items()}


def _require_thread() -> threading.Thread:
    named = [thread for thread in threading.enumerate() if thread.name == THREAD_NAME]
    assert len(named) == 1
    return named[0]


def _fail_if_called() -> bool:
    message = "shutting-down 探针不得再跑 checker"
    raise AssertionError(message)
