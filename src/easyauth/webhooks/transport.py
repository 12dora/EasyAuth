from __future__ import annotations

import socket
import ssl
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from http.client import HTTPException, HTTPResponse, HTTPSConnection
from typing import Final, final, override

from easyauth.config.net import ValidatedHttpsUrl, validate_public_https_url

RESPONSE_TOO_LARGE_MESSAGE: Final = "Webhook 响应超过允许的大小。"
REQUEST_DEADLINE_EXCEEDED_MESSAGE: Final = "Webhook 请求超过总时限。"
INVALID_CONTENT_LENGTH_MESSAGE: Final = "Webhook 响应的 Content-Length 无效。"


class WebhookTransportError(RuntimeError):
    pass


class WebhookResponseTooLargeError(WebhookTransportError):
    def __init__(self) -> None:
        super().__init__(RESPONSE_TOO_LARGE_MESSAGE)


class WebhookDeadlineExceededError(WebhookTransportError):
    def __init__(self) -> None:
        super().__init__(REQUEST_DEADLINE_EXCEEDED_MESSAGE)


@dataclass(frozen=True, slots=True)
class WebhookHttpResponse:
    status_code: int
    body: bytes
    location: str


@dataclass(frozen=True, slots=True)
class WebhookRequestPolicy:
    connect_timeout_seconds: float
    total_timeout_seconds: float
    max_response_bytes: int


@dataclass(frozen=True, slots=True)
class _OutboundRequest:
    method: str
    url: str
    allowed_hosts: tuple[str, ...]
    body: bytes | None
    headers: dict[str, str]


@final
class _PinnedHttpsConnection(HTTPSConnection):
    def __init__(
        self,
        *,
        target: ValidatedHttpsUrl,
        address: str,
        timeout: float,
    ) -> None:
        tls_context = ssl.create_default_context()
        super().__init__(
            target.hostname,
            port=target.port,
            timeout=timeout,
            context=tls_context,
        )
        self._pinned_address = address
        self._tls_context = tls_context

    @override
    def connect(self) -> None:
        # socket 只连接本次校验得到的 IP; TLS 校验证书和 SNI 仍使用原始域名。
        sock = socket.create_connection(
            (self._pinned_address, self.port),
            timeout=self.timeout,
        )
        self.sock = self._tls_context.wrap_socket(sock, server_hostname=self.host)


def post_webhook(
    *,
    url: str,
    allowed_hosts: tuple[str, ...],
    body: bytes,
    headers: dict[str, str],
    policy: WebhookRequestPolicy,
) -> WebhookHttpResponse:
    return _request_webhook(
        _OutboundRequest(
            method="POST",
            url=url,
            allowed_hosts=allowed_hosts,
            body=body,
            headers=headers,
        ),
        policy,
    )


def get_webhook(
    *,
    url: str,
    allowed_hosts: tuple[str, ...],
    headers: dict[str, str],
    policy: WebhookRequestPolicy,
) -> WebhookHttpResponse:
    return _request_webhook(
        _OutboundRequest(
            method="GET",
            url=url,
            allowed_hosts=allowed_hosts,
            body=None,
            headers=headers,
        ),
        policy,
    )


def _request_webhook(
    request: _OutboundRequest,
    policy: WebhookRequestPolicy,
) -> WebhookHttpResponse:
    started_at = time.monotonic()
    try:
        target = validate_public_https_url(
            request.url,
            allowed_hosts=request.allowed_hosts,
            dns_timeout_seconds=_remaining_seconds(started_at, policy.total_timeout_seconds),
        )
    except ValueError as error:
        raise WebhookTransportError(str(error)) from error
    remaining = _remaining_seconds(started_at, policy.total_timeout_seconds)
    connection = _PinnedHttpsConnection(
        target=target,
        address=target.addresses[0],
        timeout=min(policy.connect_timeout_seconds, remaining),
    )
    deadline_reached, deadline_timer = _start_deadline_timer(connection, remaining)
    response: HTTPResponse | None = None
    try:
        connection.request(
            request.method,
            target.request_target,
            body=request.body,
            headers=request.headers,
        )
        remaining = _remaining_seconds(started_at, policy.total_timeout_seconds)
        if connection.sock is not None:
            _ = connection.sock.settimeout(remaining)
        response = connection.getresponse()
        response_body = _read_bounded_response(
            response,
            connection=connection,
            started_at=started_at,
            total_timeout_seconds=policy.total_timeout_seconds,
            max_response_bytes=policy.max_response_bytes,
        )
        if deadline_reached.is_set():
            raise WebhookDeadlineExceededError
        return WebhookHttpResponse(
            status_code=response.status,
            body=response_body,
            location=response.getheader("Location", ""),
        )
    except TimeoutError as error:
        raise WebhookDeadlineExceededError from error
    except (HTTPException, OSError) as error:
        if deadline_reached.is_set():
            raise WebhookDeadlineExceededError from error
        raise WebhookTransportError(str(error)) from error
    finally:
        _ = deadline_timer.cancel()
        if response is not None:
            response.close()
        connection.close()


def _start_deadline_timer(
    connection: HTTPSConnection,
    remaining_seconds: float,
) -> tuple[threading.Event, threading.Timer]:
    deadline_reached = threading.Event()

    def abort_at_deadline() -> None:
        deadline_reached.set()
        if isinstance(connection.sock, socket.socket):
            with suppress(OSError):
                connection.sock.shutdown(socket.SHUT_RDWR)
        connection.close()

    timer = threading.Timer(remaining_seconds, abort_at_deadline)
    timer.daemon = True
    timer.start()
    return deadline_reached, timer


def _read_bounded_response(
    response: HTTPResponse,
    *,
    connection: HTTPSConnection,
    started_at: float,
    total_timeout_seconds: float,
    max_response_bytes: int,
) -> bytes:
    content_length = response.getheader("Content-Length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError as error:
            raise WebhookTransportError(INVALID_CONTENT_LENGTH_MESSAGE) from error
        if declared_size < 0:
            raise WebhookTransportError(INVALID_CONTENT_LENGTH_MESSAGE)
        if declared_size > max_response_bytes:
            raise WebhookResponseTooLargeError
    chunks: list[bytes] = []
    received = 0
    while True:
        remaining_time = _remaining_seconds(started_at, total_timeout_seconds)
        if connection.sock is not None:
            _ = connection.sock.settimeout(remaining_time)
        chunk = response.read1(min(8192, max_response_bytes - received + 1))
        if not chunk:
            break
        received += len(chunk)
        if received > max_response_bytes:
            raise WebhookResponseTooLargeError
        chunks.append(chunk)
    return b"".join(chunks)


def _remaining_seconds(started_at: float, total_timeout_seconds: float) -> float:
    remaining = total_timeout_seconds - (time.monotonic() - started_at)
    if remaining <= 0:
        raise WebhookDeadlineExceededError
    return remaining
