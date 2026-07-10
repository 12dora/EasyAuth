from __future__ import annotations

from typing import TYPE_CHECKING, Self

import pytest

from easyauth.integrations.dingtalk import api_client as client_module
from easyauth.integrations.dingtalk.api_client import (
    MAX_JSON_RESPONSE_BYTES,
    DingTalkApiClient,
    DingTalkApiRequestError,
    DingTalkApiUnavailableError,
)

if TYPE_CHECKING:
    from types import TracebackType
    from urllib.request import Request

TEST_APP_SECRET = "app-secret"  # noqa: S105 - 测试用假凭证。


class _Response:
    body: bytes

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.read_amounts: list[int] = []

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
        self.read_amounts.append(amount)
        return self.body[:amount]


class _Cache:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.set_calls: list[tuple[str, object, int | None]] = []

    def get(self, key: str) -> object | None:
        return self.values.get(key)

    def set(self, key: str, value: object, timeout: int | None = None) -> None:
        self.values[key] = value
        self.set_calls.append((key, value, timeout))

    def delete(self, key: str) -> None:
        _ = self.values.pop(key, None)


def _client(*, app_key: str = "app-key", app_secret: str = TEST_APP_SECRET) -> DingTalkApiClient:
    return DingTalkApiClient(
        app_key=app_key,
        app_secret=app_secret,
        timeout_seconds=5,
    )


def _patch_responses(
    monkeypatch: pytest.MonkeyPatch,
    *responses: _Response,
) -> None:
    response_iterator = iter(responses)

    def fake_urlopen(_request: Request, *, timeout: float) -> _Response:
        del timeout
        return next(response_iterator)

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)


def test_token_cache_is_scoped_by_credential_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_cache = _Cache()
    monkeypatch.setattr(client_module, "cache", fake_cache)
    _patch_responses(
        monkeypatch,
        _Response(b'{"accessToken":"token-a","expireIn":7200}'),
        _Response(b'{"accessToken":"token-b","expireIn":7200}'),
    )

    assert (
        _client(app_key="app-a", app_secret="secret-a").get_access_token()  # noqa: S106
        == "token-a"
    )
    assert (
        _client(app_key="app-b", app_secret="secret-b").get_access_token()  # noqa: S106
        == "token-b"
    )
    keys = [call[0] for call in fake_cache.set_calls]
    assert len(set(keys)) == len(fake_cache.set_calls)
    assert all("app-a" not in key and "secret-a" not in key for key in keys)


def test_token_ttl_uses_provider_expiry_and_force_refresh_bypasses_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_cache = _Cache()
    monkeypatch.setattr(client_module, "cache", fake_cache)
    _patch_responses(
        monkeypatch,
        _Response(b'{"accessToken":"token-1","expireIn":300}'),
        _Response(b'{"accessToken":"token-2","expireIn":300}'),
    )
    client = _client()

    assert client.get_access_token() == "token-1"
    assert client.get_access_token() == "token-1"
    assert client.get_access_token(force_refresh=True) == "token-2"
    assert [call[2] for call in fake_cache.set_calls] == [180, 180]


def test_token_response_requires_valid_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_responses(monkeypatch, _Response(b'{"accessToken":"token"}'))

    with pytest.raises(DingTalkApiRequestError, match="expireIn"):
        _ = _client().get_access_token(force_refresh=True)


def test_rejects_json_response_larger_than_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _Response(b"x" * (MAX_JSON_RESPONSE_BYTES + 1))
    _patch_responses(monkeypatch, response)

    with pytest.raises(DingTalkApiRequestError, match="大小限制"):
        _ = _client().get_access_token(force_refresh=True)
    assert response.read_amounts == [MAX_JSON_RESPONSE_BYTES + 1]


def test_total_deadline_includes_response_read(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter((0.0, 0.0, 6.0))
    monkeypatch.setattr(client_module, "monotonic", lambda: next(ticks))
    _patch_responses(
        monkeypatch,
        _Response(b'{"accessToken":"token","expireIn":300}'),
    )

    with pytest.raises(DingTalkApiUnavailableError):
        _ = _client().get_access_token(force_refresh=True)
