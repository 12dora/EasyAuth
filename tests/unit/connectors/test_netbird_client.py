from __future__ import annotations

from typing import TYPE_CHECKING, Self

import pytest

from easyauth.connectors.netbird import client as client_module
from easyauth.connectors.netbird.client import MAX_RESPONSE_BYTES, NetBirdApiError, NetBirdClient

if TYPE_CHECKING:
    from collections.abc import Iterator

EXPECTED_ATTEMPTS = 3
TRANSIENT_ERROR_MESSAGE = "temporary"


class _Response:
    def __init__(self, chunks: list[bytes], *, content_length: str | None = None) -> None:
        self._chunks: Iterator[bytes] = iter(chunks)
        self.headers = {} if content_length is None else {"Content-Length": content_length}
        self.read_calls = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _amount: int = -1) -> bytes:
        self.read_calls += 1
        return next(self._chunks, b"")


def _client(**kwargs: float) -> NetBirdClient:
    return NetBirdClient(
        api_url="https://netbird.example.com",
        api_token="token",  # noqa: S106 - 测试专用固定值。
        **kwargs,
    )


def test_get_account_id_requires_one_immutable_id(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response([b'[{"id":"account-1"}]'])
    monkeypatch.setattr(client_module, "urlopen", lambda *_args, **_kwargs: response)

    assert _client().get_account_id() == "account-1"


def test_list_users_rejects_non_object_elements(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response([b'[{"id":"u1","role":"user","is_blocked":false,"is_service_user":false},1]'])
    monkeypatch.setattr(client_module, "urlopen", lambda *_args, **_kwargs: response)

    with pytest.raises(NetBirdApiError, match="JSON 对象"):
        _client().list_users()


def test_list_users_rejects_unknown_role_and_duplicate_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _Response(
        [
            b'[{"id":"u1","role":"root","is_blocked":false,"is_service_user":false}]',
        ]
    )
    monkeypatch.setattr(client_module, "urlopen", lambda *_args, **_kwargs: response)
    with pytest.raises(NetBirdApiError, match="未知 role"):
        _client().list_users()

    dup = _Response(
        [
            b'[{"id":"u1","role":"user","is_blocked":false,"is_service_user":false},'
            b'{"id":"u1","role":"user","is_blocked":false,"is_service_user":false}]',
        ]
    )
    monkeypatch.setattr(client_module, "urlopen", lambda *_args, **_kwargs: dup)
    with pytest.raises(NetBirdApiError, match="重复 ID"):
        _client().list_users()


def test_rejects_oversized_content_length_before_read(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response([], content_length=str(MAX_RESPONSE_BYTES + 1))
    monkeypatch.setattr(client_module, "urlopen", lambda *_args, **_kwargs: response)

    with pytest.raises(NetBirdApiError, match="大小上限"):
        _client().list_users()
    assert response.read_calls == 0


def test_rejects_chunked_body_at_n_plus_one(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response([b"x" * MAX_RESPONSE_BYTES, b"x"])
    monkeypatch.setattr(client_module, "urlopen", lambda *_args, **_kwargs: response)

    with pytest.raises(NetBirdApiError, match="大小上限"):
        _client().list_users()


def test_rejects_slow_drip_after_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response([b"["])
    ticks = iter((0.0, 0.0, 0.0, 2.0))
    monkeypatch.setattr(client_module, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(client_module, "urlopen", lambda *_args, **_kwargs: response)

    with pytest.raises(NetBirdApiError, match="总时限"):
        _client(total_timeout_seconds=1.0).list_users()


def test_transient_get_is_retried_with_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    response = _Response([b"[]"])

    def open_response(*_args: object, **_kwargs: object) -> _Response:
        nonlocal attempts
        attempts += 1
        if attempts < EXPECTED_ATTEMPTS:
            raise TimeoutError(TRANSIENT_ERROR_MESSAGE)
        return response

    monkeypatch.setattr(client_module, "urlopen", open_response)

    assert _client().list_users() == []
    assert attempts == EXPECTED_ATTEMPTS
