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

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _client() -> EasyAuthAppClient:
    return EasyAuthAppClient(base_url="http://easyauth:8001/", app_key="my app", token="eat_x")


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
