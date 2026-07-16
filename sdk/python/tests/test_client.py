from __future__ import annotations

import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
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


def _assert_http_error_closed(error: EasyAuthClientError) -> None:
    cause = error.__cause__
    assert isinstance(cause, HTTPError)
    assert cause.closed is True
    if cause.fp is not None:
        assert cause.fp.closed is True


def test_client_error_keeps_legacy_message_and_status_code() -> None:
    error = EasyAuthClientError("legacy message", status_code=418)

    assert str(error) == "legacy message"
    assert error.status_code == 418
    assert error.error_code is None
    assert error.details == {}
    assert error.retryable is False
    assert error.transport_error is False


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
    assert excinfo.value.error_code is None
    assert excinfo.value.details == {}
    assert excinfo.value.retry_after is None
    assert excinfo.value.retry_after_seconds is None
    assert excinfo.value.retryable is False
    assert excinfo.value.transport_error is False
    assert "403" in str(excinfo.value)


def test_query_parses_unified_error_and_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "error": {
            "code": "THROTTLED",
            "message": "请求过于频繁。",
            "details": {"limit": 60},
        },
    }

    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        raise HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {"Retry-After": "120"},  # type: ignore[arg-type]
            io.BytesIO(json.dumps(payload).encode("utf-8")),
        )

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    with pytest.raises(EasyAuthClientError, match="请求过于频繁") as excinfo:
        _client().query_user_permissions("u")

    error = excinfo.value
    assert error.status_code == 429
    assert error.error_code == "THROTTLED"
    assert error.details == {"limit": 60}
    assert error.retry_after == "120"
    assert error.retry_after_seconds == 120
    assert error.retryable is True
    assert error.transport_error is False
    _assert_http_error_closed(error)


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [
        (401, False),
        (403, False),
        (404, False),
        (409, False),
        (422, False),
        (500, True),
        (503, True),
    ],
)
def test_http_error_retryability_by_status(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    retryable: bool,  # noqa: FBT001 - 参数值由 pytest 参数表驱动。
) -> None:
    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        raise HTTPError(
            request.full_url,
            status_code,
            "error",
            {},  # type: ignore[arg-type]
            io.BytesIO(b'{"error":{"code":"TEST","message":"failed","details":{}}}'),
        )

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    with pytest.raises(EasyAuthClientError) as excinfo:
        _client().query_user_permissions("u")

    assert excinfo.value.retryable is retryable
    assert excinfo.value.transport_error is False


def test_retry_after_keeps_non_integer_header_without_guessing_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        raise HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            {"Retry-After": "Wed, 21 Oct 2030 07:28:00 GMT"},  # type: ignore[arg-type]
            io.BytesIO(b""),
        )

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    with pytest.raises(EasyAuthClientError) as excinfo:
        _client().query_user_permissions("u")

    assert excinfo.value.retry_after == "Wed, 21 Oct 2030 07:28:00 GMT"
    assert excinfo.value.retry_after_seconds is None


def test_query_raises_client_error_on_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        raise URLError("connection refused")

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    with pytest.raises(EasyAuthClientError, match="无法连接") as excinfo:
        _client().query_user_permissions("u")
    assert excinfo.value.status_code is None
    assert excinfo.value.error_code is None
    assert excinfo.value.details == {}
    assert excinfo.value.retryable is True
    assert excinfo.value.transport_error is True


def test_response_read_total_timeout_is_retryable_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter((0.0, 0.0, 16.0))

    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        return _FakeResponse(b"{}")

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    monkeypatch.setattr(client_module, "monotonic", lambda: next(clock))

    with pytest.raises(EasyAuthClientError, match="总时限") as excinfo:
        _client().query_user_permissions("u")

    assert excinfo.value.retryable is True
    assert excinfo.value.transport_error is True


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
    with pytest.raises(EasyAuthClientError, match="重定向") as excinfo:
        _client().query_user_permissions("u")
    assert excinfo.value.status_code == 302
    assert excinfo.value.retryable is False
    assert excinfo.value.transport_error is False
    _assert_http_error_closed(excinfo.value)


def test_default_opener_does_not_forward_authorization_on_redirect() -> None:
    redirected_authorizations: list[str | None] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/redirected":
                redirected_authorizations.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")
                return
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://127.0.0.1:{self.server.server_port}/redirected",
            )
            self.end_headers()

        def log_message(self, _format: str, *args: object) -> None:  # noqa: ARG002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = EasyAuthAppClient(
            base_url=f"http://127.0.0.1:{server.server_port}",
            app_key="app",
            token="high-privilege-token",
            allow_insecure_http=True,
        )
        with pytest.raises(EasyAuthClientError, match="重定向") as excinfo:
            client.query_user_permissions("u")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert excinfo.value.status_code == 302
    assert redirected_authorizations == []
    _assert_http_error_closed(excinfo.value)


def test_oversized_http_error_body_is_truncated_and_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error_body = io.BytesIO(b"x" * 100)

    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        raise HTTPError(
            request.full_url,
            503,
            "Service Unavailable",
            {},  # type: ignore[arg-type]
            error_body,
        )

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    client = EasyAuthAppClient(
        base_url="http://easyauth:8001",
        app_key="app",
        token="eat_x",
        allow_insecure_http=True,
        max_response_bytes=10,
    )

    with pytest.raises(EasyAuthClientError, match=r"x{10}") as excinfo:
        client.query_user_permissions("u")

    assert excinfo.value.retryable is True
    assert error_body.closed is True
    _assert_http_error_closed(excinfo.value)


def test_rejects_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        return _FakeResponse(b"x" * 20)

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


def test_sync_manifest_posts_body_and_optional_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(json.dumps({"status": "applied", "version": 2}).encode("utf-8"))

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    result = _client().sync_manifest(
        {"schema_version": 1, "app": {"app_key": "my app"}},
        base_url="https://app.example.com",
    )

    assert result == {"status": "applied", "version": 2}
    assert captured["url"] == "http://easyauth:8001/api/v1/apps/my%20app/manifest-sync"
    assert captured["method"] == "POST"
    assert captured["body"] == {
        "manifest": {"schema_version": 1, "app": {"app_key": "my app"}},
        "base_url": "https://app.example.com",
    }


def test_list_approval_templates_and_list_approvals(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        captured.append(request.full_url)
        if request.full_url.endswith("/approval-templates"):
            return _FakeResponse(json.dumps({"data": [{"key": "expense"}]}).encode("utf-8"))
        return _FakeResponse(
            json.dumps({"data": [], "pagination": {"page": 1, "page_size": 20}}).encode("utf-8")
        )

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    templates = _client().list_approval_templates()
    approvals = _client().list_approvals(
        status="submitted", biz_key="order-1", page=2, page_size=10
    )

    assert templates == {"data": [{"key": "expense"}]}
    assert approvals["pagination"]["page"] == 1
    assert captured[0] == "http://easyauth:8001/api/v1/apps/my%20app/approval-templates"
    assert "status=submitted" in captured[1]
    assert "biz_key=order-1" in captured[1]
    assert "page=2" in captured[1]
    assert "page_size=10" in captured[1]
