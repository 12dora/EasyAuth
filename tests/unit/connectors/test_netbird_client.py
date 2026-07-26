from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final

import pytest

from easyauth.connectors.netbird import client as client_module
from easyauth.connectors.netbird.client import (
    GROUP_PAGE_SIZE,
    MAX_GROUP_PAGES,
    MAX_RESPONSE_BYTES,
    NetBirdApiError,
    NetBirdClient,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

EXPECTED_ATTEMPTS = 3
TRANSIENT_ERROR_MESSAGE = "temporary"


class _UrlRequest(Protocol):
    @property
    def full_url(self) -> str: ...


class _UrlOpenStub(Protocol):
    def __call__(
        self,
        request: _UrlRequest,
        *,
        timeout: float,
    ) -> _Response: ...


@final
class _Response:
    def __init__(self, chunks: list[bytes], *, content_length: str | None = None) -> None:
        self._chunks: Iterator[bytes] = iter(chunks)
        self.headers: dict[str, str] = (
            {} if content_length is None else {"Content-Length": content_length}
        )
        self.read_calls: int = 0

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


def _static_response(response: _Response) -> _UrlOpenStub:
    def open_response(request: _UrlRequest, *, timeout: float) -> _Response:
        _ = (request, timeout)
        return response

    return open_response


def test_get_account_id_requires_one_immutable_id(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response([b'[{"id":"account-1"}]'])
    monkeypatch.setattr(client_module, "urlopen", _static_response(response))

    assert _client().get_account_id() == "account-1"


def test_list_users_rejects_non_object_elements(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response(
        [b'[{"id":"u1","role":"user","is_blocked":false,"is_service_user":false},1]'],
    )
    monkeypatch.setattr(client_module, "urlopen", _static_response(response))

    with pytest.raises(NetBirdApiError, match="JSON 对象"):
        _ = _client().list_users()


def test_list_users_rejects_unknown_role_and_duplicate_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _Response(
        [
            b'[{"id":"u1","role":"root","is_blocked":false,"is_service_user":false}]',
        ]
    )
    monkeypatch.setattr(client_module, "urlopen", _static_response(response))
    with pytest.raises(NetBirdApiError, match="未知 role"):
        _ = _client().list_users()

    dup = _Response(
        [
            (
                b'[{"id":"u1","role":"user","is_blocked":false,"is_service_user":false},'
                b'{"id":"u1","role":"user","is_blocked":false,"is_service_user":false}]'
            ),
        ]
    )
    monkeypatch.setattr(client_module, "urlopen", _static_response(dup))
    with pytest.raises(NetBirdApiError, match="重复 ID"):
        _ = _client().list_users()


def test_rejects_oversized_content_length_before_read(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response([], content_length=str(MAX_RESPONSE_BYTES + 1))
    monkeypatch.setattr(client_module, "urlopen", _static_response(response))

    with pytest.raises(NetBirdApiError, match="大小上限"):
        _ = _client().list_users()
    assert response.read_calls == 0


def test_rejects_chunked_body_at_n_plus_one(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response([b"x" * MAX_RESPONSE_BYTES, b"x"])
    monkeypatch.setattr(client_module, "urlopen", _static_response(response))

    with pytest.raises(NetBirdApiError, match="大小上限"):
        _ = _client().list_users()


def test_rejects_slow_drip_after_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response([b"["])
    ticks = iter((0.0, 0.0, 0.0, 2.0))
    monkeypatch.setattr(client_module, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(client_module, "urlopen", _static_response(response))

    with pytest.raises(NetBirdApiError, match="总时限"):
        _ = _client(total_timeout_seconds=1.0).list_users()


def test_transient_get_is_retried_with_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0
    response = _Response([b"[]"])

    def open_response(request: _UrlRequest, *, timeout: float) -> _Response:
        _ = (request, timeout)
        nonlocal attempts
        attempts += 1
        if attempts < EXPECTED_ATTEMPTS:
            raise TimeoutError(TRANSIENT_ERROR_MESSAGE)
        return response

    monkeypatch.setattr(client_module, "urlopen", open_response)

    assert _client().list_users() == []
    assert attempts == EXPECTED_ATTEMPTS


def test_iter_group_pages_stops_on_short_page(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_paths: list[str] = []

    def open_response(request: _UrlRequest, *, timeout: float) -> _Response:
        _ = timeout
        seen_paths.append(request.full_url)
        if len(seen_paths) == 1:
            return _Response([b'[{"id":"g1","name":"VPN A"}]'])
        return _Response([b"[]"])

    monkeypatch.setattr(client_module, "urlopen", open_response)

    pages = _client().iter_group_pages()

    assert [[group.group_id for group in page] for page in pages] == [["g1"]]
    assert seen_paths[0].endswith(f"/api/groups?page=1&page_size={GROUP_PAGE_SIZE}")


def test_iter_group_pages_fails_when_upstream_does_not_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def full_page_response(request: _UrlRequest, *, timeout: float) -> _Response:
        _ = timeout
        page = request.full_url.split("page=", maxsplit=1)[1].split("&", maxsplit=1)[0]
        full_page = (
            "["
            + ",".join(
                f'{{"id":"g{page}-{index}","name":"VPN {page}-{index}"}}'
                for index in range(GROUP_PAGE_SIZE)
            )
            + "]"
        ).encode()
        return _Response([full_page])

    monkeypatch.setattr(client_module, "urlopen", full_page_response)

    with pytest.raises(NetBirdApiError, match=str(MAX_GROUP_PAGES)):
        _ = _client().iter_group_pages()
