from __future__ import annotations

from json import dumps
from typing import TYPE_CHECKING, Self, final

import pytest

from easyauth.integrations.authentik.admin_client import (
    OPERATION_TIMEOUT_MESSAGE,
    RESPONSE_TOO_LARGE_MESSAGE,
    AuthentikAdminClient,
    AuthentikAdminError,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType
    from urllib.request import Request

_OVERSIZED_BODY_BYTES = 1024 * 1024 + 1
_EXPECTED_SESSION_COUNT = 3


@final
class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        content_length: str | None = None,
        omit_content_length: bool = False,
    ) -> None:
        self._body: bytes = body
        self._offset: int = 0
        self._content_length: str | None = (
            None
            if omit_content_length
            else (str(len(body)) if content_length is None else content_length)
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        if amount < 0:
            amount = len(self._body) - self._offset
        chunk = self._body[self._offset : self._offset + amount]
        self._offset += len(chunk)
        return chunk

    def getheader(self, name: str) -> str | None:
        return self._content_length if name == "Content-Length" else None


def _json_response(payload: object) -> _Response:
    return _Response(dumps(payload).encode())


def _client(*, monotonic: Callable[[], float] | None = None) -> AuthentikAdminClient:
    if monotonic is None:
        return AuthentikAdminClient(
            base_url="https://authentik.test",
            api_token="test-token",  # noqa: S106 - 测试假 token.
            timeout_seconds=5,
        )
    return AuthentikAdminClient(
        base_url="https://authentik.test",
        api_token="test-token",  # noqa: S106 - 测试假 token.
        timeout_seconds=5,
        monotonic=monotonic,
    )


def _user_page() -> dict[str, object]:
    return {
        "results": [{"uid": "user-uid", "pk": 7}],
        "pagination": {"total_pages": 1},
    }


def _session_page(*uuids: str, current: int, next_page: int) -> dict[str, object]:
    return {
        "results": [{"uuid": value} for value in uuids],
        "pagination": {"current": current, "next": next_page},
    }


def _urlopen_response(response: _Response) -> Callable[..., _Response]:
    def fake_urlopen(_request: Request, *, timeout: float) -> _Response:
        _ = timeout
        return response

    return fake_urlopen


def test_disable_user_revokes_every_session_page(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            _json_response(_user_page()),
            _json_response({}),
            _json_response(_session_page("session-1", "session-2", current=1, next_page=2)),
            _json_response(_session_page("session-3", current=2, next_page=0)),
            _Response(b""),
            _Response(b""),
            _Response(b""),
        ],
    )
    seen_urls: list[str] = []

    def fake_urlopen(request: Request, *, timeout: float) -> _Response:
        assert timeout > 0
        seen_urls.append(request.full_url)
        return next(responses)

    monkeypatch.setattr("easyauth.integrations.authentik.admin_client.urlopen", fake_urlopen)

    result = _client().disable_user_and_revoke_sessions("user-uid")

    assert result.revoked_session_count == _EXPECTED_SESSION_COUNT
    session_list_urls = [url for url in seen_urls if "authenticated_sessions/?" in url]
    assert session_list_urls == [
        "https://authentik.test/api/v3/core/authenticated_sessions/?user=7&page=1&page_size=500",
        "https://authentik.test/api/v3/core/authenticated_sessions/?user=7&page=2&page_size=500",
    ]
    assert (
        sum("authenticated_sessions/session-" in url for url in seen_urls)
        == _EXPECTED_SESSION_COUNT
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"results": None, "pagination": {"current": 1, "next": 0}},
        {"results": ["bad-item"], "pagination": {"current": 1, "next": 0}},
        {"results": [{"uuid": 123}], "pagination": {"current": 1, "next": 0}},
        {"results": [], "pagination": {"current": 2, "next": 0}},
    ],
)
def test_session_revoke_rejects_malformed_envelope(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    responses = iter(
        [
            _json_response(_user_page()),
            _json_response({}),
            _json_response(payload),
        ],
    )
    def fake_urlopen(_request: Request, *, timeout: float) -> _Response:
        _ = timeout
        return next(responses)

    monkeypatch.setattr("easyauth.integrations.authentik.admin_client.urlopen", fake_urlopen)

    with pytest.raises(AuthentikAdminError, match="响应格式"):
        _ = _client().disable_user_and_revoke_sessions("user-uid")


def test_request_rejects_declared_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response(b"{}", content_length=str(_OVERSIZED_BODY_BYTES))
    monkeypatch.setattr(
        "easyauth.integrations.authentik.admin_client.urlopen",
        _urlopen_response(response),
    )

    with pytest.raises(AuthentikAdminError, match=RESPONSE_TOO_LARGE_MESSAGE):
        _ = _client()._request_json(  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
            "GET",
            "/api/v3/test/",
        )


def test_request_rejects_streamed_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response(b"x" * _OVERSIZED_BODY_BYTES, omit_content_length=True)
    monkeypatch.setattr(
        "easyauth.integrations.authentik.admin_client.urlopen",
        _urlopen_response(response),
    )

    with pytest.raises(AuthentikAdminError, match=RESPONSE_TOO_LARGE_MESSAGE):
        _ = _client()._request_json(  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
            "GET",
            "/api/v3/test/",
        )


def test_request_enforces_total_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter([0.0, 0.0, 61.0]).__next__
    monkeypatch.setattr(
        "easyauth.integrations.authentik.admin_client.urlopen",
        _urlopen_response(_json_response({})),
    )

    with pytest.raises(AuthentikAdminError, match=OPERATION_TIMEOUT_MESSAGE):
        _ = _client(monotonic=clock)._request_json(  # pyright: ignore[reportPrivateUsage]  # noqa: SLF001
            "GET",
            "/api/v3/test/",
        )
