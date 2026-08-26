"""有界 HTTP 响应读取: 限制体积与总时限。"""

from __future__ import annotations

import socket
import time
from typing import TYPE_CHECKING, Final, Protocol, Self

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

HTTP_RESPONSE_TOO_LARGE_MESSAGE = "外部 HTTP 响应超过允许的大小。"
HTTP_RESPONSE_DEADLINE_MESSAGE = "外部 HTTP 响应读取超过总时限。"
HTTP_INVALID_CONTENT_LENGTH_MESSAGE = "外部 HTTP 响应的 Content-Length 无效。"
HTTP_READ_CHUNK_BYTES: Final = 64 * 1024

__all__ = (
    "HTTP_INVALID_CONTENT_LENGTH_MESSAGE",
    "HTTP_RESPONSE_DEADLINE_MESSAGE",
    "HTTP_RESPONSE_TOO_LARGE_MESSAGE",
    "HeaderReadableResponse",
    "HttpResponseDeadlineExceededError",
    "HttpResponseReadError",
    "HttpResponseTooLargeError",
    "InvalidContentLengthError",
    "read_urlopen_body_bounded",
)


class HttpResponseReadError(RuntimeError):
    pass


class HttpResponseTooLargeError(HttpResponseReadError):
    def __init__(self) -> None:
        super().__init__(HTTP_RESPONSE_TOO_LARGE_MESSAGE)


class HttpResponseDeadlineExceededError(HttpResponseReadError):
    def __init__(self) -> None:
        super().__init__(HTTP_RESPONSE_DEADLINE_MESSAGE)


class InvalidContentLengthError(HttpResponseReadError):
    def __init__(self) -> None:
        super().__init__(HTTP_INVALID_CONTENT_LENGTH_MESSAGE)


class HeaderReadableResponse(Protocol):
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def read(self, amount: int = -1) -> bytes: ...

    def getheader(self, name: str) -> str | None: ...


def read_urlopen_body_bounded(
    response: HeaderReadableResponse,
    *,
    started_at: float,
    total_timeout_seconds: float,
    max_response_bytes: int,
    monotonic: Callable[[], float] = time.monotonic,
) -> bytes:
    content_length = response.getheader("Content-Length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise InvalidContentLengthError from error
        if declared_length < 0:
            raise InvalidContentLengthError
        if declared_length > max_response_bytes:
            raise HttpResponseTooLargeError

    chunks: list[bytes] = []
    observed = 0
    while True:
        remaining = _remaining_response_deadline_seconds(
            started_at=started_at,
            total_timeout_seconds=total_timeout_seconds,
            monotonic=monotonic,
        )
        _set_response_socket_timeout(response, remaining)
        chunk = response.read(min(HTTP_READ_CHUNK_BYTES, max_response_bytes + 1 - observed))
        _ = _remaining_response_deadline_seconds(
            started_at=started_at,
            total_timeout_seconds=total_timeout_seconds,
            monotonic=monotonic,
        )
        if not chunk:
            return b"".join(chunks)
        observed += len(chunk)
        if observed > max_response_bytes:
            raise HttpResponseTooLargeError
        chunks.append(chunk)


def _remaining_response_deadline_seconds(
    *,
    started_at: float,
    total_timeout_seconds: float,
    monotonic: Callable[[], float],
) -> float:
    remaining = total_timeout_seconds - (monotonic() - started_at)
    if remaining <= 0:
        raise HttpResponseDeadlineExceededError
    return remaining


def _set_response_socket_timeout(response: object, timeout_seconds: float) -> None:
    socket_candidate = _response_socket_candidate(response)
    if isinstance(socket_candidate, socket.socket):
        socket_candidate.settimeout(timeout_seconds)


def _response_socket_candidate(response: object) -> object | None:
    current: object | None = response
    for attribute in ("fp", "raw", "_sock"):
        current = getattr(current, attribute, None)
        if current is None:
            return None
    return current
