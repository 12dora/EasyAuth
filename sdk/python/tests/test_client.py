from __future__ import annotations

import io
import json
from typing import Any, Self
from urllib.error import HTTPError, URLError

import pytest
from easyauth_app_sdk import EasyAuthAppClient, EasyAuthClientError
from easyauth_app_sdk import client as client_module


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self._offset = 0
        self.headers: dict[str, str] = {}
        self.status = 200

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        if amount is None or amount < 0:
            chunk = self._body[self._offset :]
            self._offset = len(self._body)
            return chunk
        chunk = self._body[self._offset : self._offset + amount]
        self._offset += len(chunk)
        return chunk


def _client() -> EasyAuthAppClient:
    return EasyAuthAppClient(
        base_url="http://easyauth:8001/",
        app_key="my app",
        token="eat_x",
        allow_insecure_http=True,
    )


def test_query_returns_dict_payload_and_encodes_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        captured["url"] = request.full_url
        return _FakeResponse(json.dumps({"groups": [], "grants": []}).encode("utf-8"))

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    result = _client().query_user_permissions("ak/uid?x")

    assert result == {"groups": [], "grants": []}
    # base_url 末尾斜杠被规整, app_key/user_id 中的特殊字符被完整转义。
    assert captured["url"] == (
        "http://easyauth:8001/api/v1/apps/my%20app/users/ak%2Fuid%3Fx/permissions"
    )


def test_query_raises_client_error_with_status_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        raise HTTPError(
            request.full_url,
            403,
            "Forbidden",
            {},  # type: ignore[arg-type]
            io.BytesIO(b'{"error":"denied"}'),
        )

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    with pytest.raises(EasyAuthClientError) as excinfo:
        _client().query_user_permissions("u")
    assert excinfo.value.status_code == 403
    assert "403" in str(excinfo.value)


def test_query_raises_client_error_on_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        raise URLError("connection refused")

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    with pytest.raises(EasyAuthClientError, match="无法连接"):
        _client().query_user_permissions("u")


def test_query_raises_client_error_on_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        return _FakeResponse(b"not-json")

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    with pytest.raises(EasyAuthClientError, match="JSON"):
        _client().query_user_permissions("u")


def test_query_raises_client_error_on_non_dict_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        return _FakeResponse(b"[1, 2, 3]")

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    with pytest.raises(EasyAuthClientError, match="格式无效"):
        _client().query_user_permissions("u")


def test_rejects_insecure_http_by_default() -> None:
    client = EasyAuthAppClient(base_url="http://evil.example.com", app_key="app", token="eat_x")
    with pytest.raises(EasyAuthClientError, match="https"):
        client.query_user_permissions("u")


def test_rejects_redirect_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        raise HTTPError(
            request.full_url,
            302,
            "Found",
            {"Location": "https://evil.example.com/"},  # type: ignore[arg-type]
            io.BytesIO(b""),
        )

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    with pytest.raises(EasyAuthClientError, match="重定向"):
        _client().query_user_permissions("u")


def test_rejects_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        response = _FakeResponse(b"x" * 20)
        return response

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    client = EasyAuthAppClient(
        base_url="http://easyauth:8001",
        app_key="app",
        token="eat_x",
        allow_insecure_http=True,
        max_response_bytes=10,
    )
    with pytest.raises(EasyAuthClientError, match="大小上限"):
        client.query_user_permissions("u")
