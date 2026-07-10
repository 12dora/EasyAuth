from __future__ import annotations

import threading
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Self

import pytest

from easyauth.config.net import ValidatedHttpsUrl
from easyauth.webhooks import transport
from easyauth.webhooks.transport import (
    WebhookDeadlineExceededError,
    WebhookRequestPolicy,
    WebhookResponseTooLargeError,
    post_webhook,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


class _FakeSocket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)


class _FakeResponse:
    status = HTTPStatus.OK

    def __init__(self, chunks: list[bytes], *, content_length: str | None = None) -> None:
        self._chunks = iter(chunks)
        self._content_length = content_length

    def read1(self, _size: int) -> bytes:
        return next(self._chunks, b"")

    def getheader(self, name: str, default: str | None = None) -> str | None:
        if name == "Content-Length":
            return self._content_length
        return default

    def close(self) -> None:
        return None


class _FakeConnection:
    response = _FakeResponse([b"{}"])
    instances: ClassVar[list[Self]] = []

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.sock = _FakeSocket()
        self.request_args: tuple[object, ...] = ()
        self.__class__.instances.append(self)

    def request(self, *args: object, **_kwargs: object) -> None:
        self.request_args = args

    def getresponse(self) -> _FakeResponse:
        return self.response

    def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _transport_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeConnection.instances.clear()
    _FakeConnection.response = _FakeResponse([b"{}"])

    def validate(*_args: object, **_kwargs: object) -> ValidatedHttpsUrl:
        return ValidatedHttpsUrl(
            hostname="hooks.example.com",
            port=443,
            request_target="/callback",
            addresses=("8.8.8.8",),
        )

    monkeypatch.setattr(transport, "validate_public_https_url", validate)
    monkeypatch.setattr(transport, "_PinnedHttpsConnection", _FakeConnection)


def _policy(*, max_response_bytes: int = 16) -> WebhookRequestPolicy:
    return WebhookRequestPolicy(
        connect_timeout_seconds=1,
        total_timeout_seconds=5,
        max_response_bytes=max_response_bytes,
    )


def test_post_webhook_connects_to_validated_ip_without_reresolving() -> None:
    result = post_webhook(
        url="https://hooks.example.com/callback",
        allowed_hosts=("hooks.example.com",),
        body=b"{}",
        headers={"Content-Type": "application/json"},
        policy=_policy(),
    )

    connection = _FakeConnection.instances[0]
    assert connection.kwargs["address"] == "8.8.8.8"
    assert connection.request_args[:2] == ("POST", "/callback")
    assert result.body == b"{}"


def test_post_webhook_rejects_declared_oversized_response() -> None:
    _FakeConnection.response = _FakeResponse([], content_length="17")

    with pytest.raises(WebhookResponseTooLargeError):
        _ = post_webhook(
            url="https://hooks.example.com/callback",
            allowed_hosts=("hooks.example.com",),
            body=b"{}",
            headers={},
            policy=_policy(),
        )


def test_post_webhook_rejects_chunked_oversized_response() -> None:
    _FakeConnection.response = _FakeResponse([b"12345678", b"901234567"])

    with pytest.raises(WebhookResponseTooLargeError):
        _ = post_webhook(
            url="https://hooks.example.com/callback",
            allowed_hosts=("hooks.example.com",),
            body=b"{}",
            headers={},
            policy=_policy(),
        )


def test_post_webhook_enforces_total_deadline_during_body_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic_values: Iterator[float] = iter((0.0, 0.1, 0.2, 6.0))
    monkeypatch.setattr(transport.time, "monotonic", lambda: next(monotonic_values))

    with pytest.raises(WebhookDeadlineExceededError):
        _ = post_webhook(
            url="https://hooks.example.com/callback",
            allowed_hosts=("hooks.example.com",),
            body=b"{}",
            headers={},
            policy=_policy(),
        )


def test_post_webhook_enforces_total_deadline_while_waiting_for_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_headers = threading.Event()

    class BlockingConnection(_FakeConnection):
        def getresponse(self) -> _FakeResponse:
            _ = release_headers.wait(timeout=1)
            raise OSError

        def close(self) -> None:
            release_headers.set()

    monkeypatch.setattr(transport, "_PinnedHttpsConnection", BlockingConnection)

    with pytest.raises(WebhookDeadlineExceededError):
        _ = post_webhook(
            url="https://hooks.example.com/callback",
            allowed_hosts=("hooks.example.com",),
            body=b"{}",
            headers={},
            policy=WebhookRequestPolicy(
                connect_timeout_seconds=0.01,
                total_timeout_seconds=0.01,
                max_response_bytes=16,
            ),
        )
