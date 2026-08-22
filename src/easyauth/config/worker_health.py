from __future__ import annotations

import json
import logging
import os
import socket
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Final, Protocol, cast, override
from urllib.parse import urlsplit

from celery.signals import worker_ready, worker_shutdown, worker_shutting_down

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

LOGGER = logging.getLogger(__name__)

HEALTH_PATH: Final = "/health"
HEALTH_PORT_ENV: Final = "EASYAUTH_WORKER_HEALTH_PORT"
DEFAULT_HEALTH_PORT: Final = 8002
MAX_TCP_PORT: Final = 65535
PING_TIMEOUT_SECONDS: Final = 2.0
CHECK_TIMEOUT_SECONDS: Final = 4.0
WORKER_PING_FAILED_MESSAGE: Final = "worker ping failed"
CHECK_TIMEOUT_MESSAGE: Final = "health check timed out"
CHECK_IN_PROGRESS_MESSAGE: Final = "check in progress"
SHUTTING_DOWN_MESSAGE: Final = "shutting down"
PONG_PAYLOAD: Final = {"ok": "pong"}
THREAD_NAME: Final = "easyauth-worker-health"
CHECK_THREAD_NAME: Final = "easyauth-worker-health-check"
_JOIN_TIMEOUT_SECONDS: Final = 2.0
_READY_DISPATCH_UID: Final = "easyauth.worker_health.worker_ready"
_SHUTDOWN_DISPATCH_UID: Final = "easyauth.worker_health.worker_shutdown"
_SHUTTING_DOWN_DISPATCH_UID: Final = "easyauth.worker_health.worker_shutting_down"


class WorkerControl(Protocol):
    def ping(self, destination: list[str], timeout: float) -> object: ...


class WorkerApp(Protocol):
    control: WorkerControl


class _CelerySignal(Protocol):
    def connect(
        self,
        receiver: Callable[..., object],
        *,
        weak: bool,
        dispatch_uid: str,
    ) -> object: ...


class _HealthServerState:
    lock: threading.Lock
    server: ThreadingHTTPServer | None
    thread: threading.Thread | None
    signals_connected: bool
    shutting_down: threading.Event
    check_lock: threading.Lock

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.server = None
        self.thread = None
        self.signals_connected = False
        self.shutting_down = threading.Event()
        self.check_lock = threading.Lock()


class WorkerHealthHTTPServer(ThreadingHTTPServer):
    allow_reuse_address: bool = True
    daemon_threads: bool = True


_STATE = _HealthServerState()


def worker_health_port() -> int:
    raw = os.environ.get(HEALTH_PORT_ENV)
    if raw is None:
        return DEFAULT_HEALTH_PORT
    stripped = raw.strip()
    if stripped == "":
        message = f"{HEALTH_PORT_ENV} 不能为空"
        raise ValueError(message)
    try:
        port = int(stripped)
    except ValueError as error:
        message = f"{HEALTH_PORT_ENV} 必须是 0..{MAX_TCP_PORT} 的整数, 收到 {raw!r}"
        raise ValueError(message) from error
    if port < 0 or port > MAX_TCP_PORT:
        message = f"{HEALTH_PORT_ENV} 必须是 0..{MAX_TCP_PORT} 的整数, 收到 {raw!r}"
        raise ValueError(message)
    return port


def check_worker_ping(app: WorkerApp, worker_hostname: str) -> bool:
    try:
        replies = app.control.ping(
            destination=[worker_hostname],
            timeout=PING_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001 - 健康探针不得把 ping 异常抛出 worker 进程.
        LOGGER.warning("worker 健康检查: 本进程 ping 失败", exc_info=True)
        return False
    return _reply_has_pong(replies, worker_hostname)


def health_response(
    path: str,
    *,
    checker: Callable[[], bool],
    worker_hostname: str,
) -> tuple[HTTPStatus, dict[str, str]]:
    if path != HEALTH_PATH:
        return HTTPStatus.NOT_FOUND, {"error": "not found"}
    if _STATE.shutting_down.is_set():
        return HTTPStatus.SERVICE_UNAVAILABLE, {
            "status": "error",
            "error": SHUTTING_DOWN_MESSAGE,
        }
    return _run_bounded_check(checker, worker_hostname)


def build_health_handler(
    *,
    checker: Callable[[], bool],
    worker_hostname: str,
) -> type[BaseHTTPRequestHandler]:
    class WorkerHealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            status, payload = health_response(
                urlsplit(self.path).path,
                checker=checker,
                worker_hostname=worker_hostname,
            )
            _send_json(self, status, payload)

        @override
        def log_message(self, format: str, *args: object) -> None:
            LOGGER.debug("%s - %s", self.address_string(), format % args)

    return WorkerHealthHandler


def start_worker_health_server(
    app: WorkerApp,
    *,
    host: str = "127.0.0.1",
    port: int | None = None,
    worker_hostname: str | None = None,
    checker: Callable[[], bool] | None = None,
) -> ThreadingHTTPServer:
    resolved_port = worker_health_port() if port is None else port
    resolved_hostname = socket.gethostname() if worker_hostname is None else worker_hostname
    resolved_checker = (
        (lambda: check_worker_ping(app, resolved_hostname)) if checker is None else checker
    )
    with _STATE.lock:
        existing = _STATE.server
        if existing is not None:
            return existing
        handler = build_health_handler(
            checker=resolved_checker,
            worker_hostname=resolved_hostname,
        )
        server = WorkerHealthHTTPServer((host, resolved_port), handler)
        thread = threading.Thread(
            target=server.serve_forever,
            name=THREAD_NAME,
            daemon=True,
        )
        _STATE.server = server
        _STATE.thread = thread
        thread.start()
        return server


def stop_worker_health_server() -> None:
    with _STATE.lock:
        server = _STATE.server
        thread = _STATE.thread
        _STATE.server = None
        _STATE.thread = None
    if server is not None:
        server.shutdown()
        server.server_close()
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=_JOIN_TIMEOUT_SECONDS)
        if thread.is_alive():
            LOGGER.warning("worker 健康检查线程在关闭时仍未退出")
    _STATE.shutting_down.clear()


def connect_worker_health_signals() -> None:
    with _STATE.lock:
        if _STATE.signals_connected:
            return
        _ = _celery_signal(worker_ready).connect(
            _on_worker_ready,
            weak=False,
            dispatch_uid=_READY_DISPATCH_UID,
        )
        _ = _celery_signal(worker_shutdown).connect(
            _on_worker_shutdown,
            weak=False,
            dispatch_uid=_SHUTDOWN_DISPATCH_UID,
        )
        _ = _celery_signal(worker_shutting_down).connect(
            _on_worker_shutting_down,
            weak=False,
            dispatch_uid=_SHUTTING_DOWN_DISPATCH_UID,
        )
        _STATE.signals_connected = True


def bound_health_port(server: ThreadingHTTPServer) -> int:
    return server.server_address[1]


def _run_bounded_check(
    checker: Callable[[], bool],
    worker_hostname: str,
) -> tuple[HTTPStatus, dict[str, str]]:
    check_lock = _STATE.check_lock
    if not check_lock.acquire(blocking=False):
        return HTTPStatus.SERVICE_UNAVAILABLE, {
            "status": "error",
            "error": CHECK_IN_PROGRESS_MESSAGE,
        }
    outcome: list[bool] = []

    def run() -> None:
        try:
            outcome.append(checker())
        except Exception:  # noqa: BLE001 - 健康探针不得把 checker 异常抛出 handler 线程.
            LOGGER.warning("worker 健康检查: checker 异常", exc_info=True)
            outcome.append(False)
        finally:
            check_lock.release()

    thread = threading.Thread(target=run, name=CHECK_THREAD_NAME, daemon=True)
    thread.start()
    thread.join(timeout=CHECK_TIMEOUT_SECONDS)
    if thread.is_alive():
        return HTTPStatus.SERVICE_UNAVAILABLE, {
            "status": "error",
            "error": CHECK_TIMEOUT_MESSAGE,
        }
    if outcome and outcome[0]:
        return HTTPStatus.OK, {"status": "ok", "worker": worker_hostname}
    return HTTPStatus.SERVICE_UNAVAILABLE, {
        "status": "error",
        "error": WORKER_PING_FAILED_MESSAGE,
    }


def _reply_has_pong(replies: object, worker_hostname: str) -> bool:
    if not isinstance(replies, list):
        return False
    for item in cast("list[object]", replies):
        if not isinstance(item, dict):
            continue
        typed_item = cast("Mapping[object, object]", item)
        if typed_item.get(worker_hostname) == PONG_PAYLOAD:
            return True
    return False


def _send_json(
    handler: BaseHTTPRequestHandler,
    status: HTTPStatus,
    payload: Mapping[str, str],
) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(int(status))
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Connection", "close")
    handler.end_headers()
    _ = handler.wfile.write(body)


def _celery_signal(signal: object) -> _CelerySignal:
    return cast("_CelerySignal", signal)


def _on_worker_ready(sender: object | None = None, **_kwargs: object) -> None:
    if sender is None:
        message = "worker_ready 缺少 sender"
        raise TypeError(message)
    hostname = getattr(sender, "hostname", None)
    worker_hostname = hostname if isinstance(hostname, str) and hostname else socket.gethostname()
    _ = start_worker_health_server(
        _worker_app_from_sender(sender),
        worker_hostname=worker_hostname,
    )


def _on_worker_shutdown(**_kwargs: object) -> None:
    stop_worker_health_server()


def _on_worker_shutting_down(**_kwargs: object) -> None:
    _STATE.shutting_down.set()


def _worker_app_from_sender(sender: object) -> WorkerApp:
    app = getattr(sender, "app", None)
    control = getattr(app, "control", None)
    ping = getattr(control, "ping", None)
    if app is None or not callable(ping):
        message = "Celery worker 信号 sender 必须提供带 control.ping 的 app"
        raise TypeError(message)
    return cast("WorkerApp", app)
