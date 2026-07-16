"""directory / notify 客户端方法: 用 stub server 回放 contract_samples 样例。"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Self
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest
from easyauth_app_sdk import (
    DINGTALK_REF_PREFIX,
    NOTIFY_TEMPLATE_ACTION_CARD,
    NOTIFY_TEMPLATE_MARKDOWN,
    NOTIFY_TEMPLATE_TEXT,
    EasyAuthAppClient,
    EasyAuthClientError,
)
from easyauth_app_sdk import client as client_module

# 仓库根下的契约样例(与服务端契约测试共用)。
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SAMPLES = _REPO_ROOT / "tests" / "contract_samples"


def _load_sample(relative: str) -> dict[str, Any]:
    return json.loads((_SAMPLES / relative).read_text(encoding="utf-8"))


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


def _stub_json(monkeypatch: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """拦截 urlopen, 返回固定 JSON, 并把请求细节写入 captured。"""
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["authorization"] = request.get_header("Authorization")
        if request.data is not None:
            captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    return captured


def _assert_bearer(captured: dict[str, Any]) -> None:
    assert captured["authorization"] == "Bearer eat_x"


def test_constants_exported() -> None:
    assert NOTIFY_TEMPLATE_TEXT == "text"
    assert NOTIFY_TEMPLATE_MARKDOWN == "markdown"
    assert NOTIFY_TEMPLATE_ACTION_CARD == "action_card"
    assert DINGTALK_REF_PREFIX == "dt:"


def test_search_directory_users_url_and_query(monkeypatch: Any) -> None:
    sample = _load_sample("directory/users_list.json")
    captured = _stub_json(monkeypatch, sample)

    result = _client().search_directory_users(
        q="王",
        department_id="460001",
        manager_id="dt:manager8836",
        include_inactive=True,
        snapshot_id=sample["directory_snapshot"]["snapshot_id"],
        page=2,
        page_size=50,
    )

    assert result == sample
    _assert_bearer(captured)
    parsed = urlparse(captured["url"])
    assert parsed.path == "/api/v1/apps/my%20app/directory/users"
    query = parse_qs(parsed.query)
    assert query["q"] == ["王"]
    assert query["department_id"] == ["460001"]
    assert query["manager_id"] == ["dt:manager8836"]
    assert query["include_inactive"] == ["true"]
    assert query["snapshot_id"] == [sample["directory_snapshot"]["snapshot_id"]]
    assert query["page"] == ["2"]
    assert query["page_size"] == ["50"]
    assert captured["method"] == "GET"


def test_search_directory_users_omits_include_inactive_when_false(monkeypatch: Any) -> None:
    sample = _load_sample("directory/users_list.json")
    captured = _stub_json(monkeypatch, sample)

    _ = _client().search_directory_users(page=1, page_size=20)

    _assert_bearer(captured)
    query = parse_qs(urlparse(captured["url"]).query)
    assert "include_inactive" not in query
    assert "snapshot_id" not in query
    assert "q" not in query
    assert query["page"] == ["1"]
    assert query["page_size"] == ["20"]


def test_search_directory_users_omits_empty_snapshot_id(monkeypatch: Any) -> None:
    sample = _load_sample("directory/users_list.json")
    captured = _stub_json(monkeypatch, sample)

    _ = _client().search_directory_users(snapshot_id="")

    assert "snapshot_id" not in parse_qs(urlparse(captured["url"]).query)


def test_search_directory_users_snapshot_conflict_is_structured_and_not_retried(
    monkeypatch: Any,
) -> None:
    calls = 0
    payload = {
        "error": {
            "code": "CONFLICT",
            "message": "目录快照已变化, 请从第一页重新开始。",
            "details": {
                "expected_snapshot_id": "snapshot-old",
                "actual_snapshot_id": "snapshot-new",
            },
        },
    }

    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        nonlocal calls
        calls += 1
        raise HTTPError(
            request.full_url,
            409,
            "Conflict",
            {},  # type: ignore[arg-type]
            io.BytesIO(json.dumps(payload).encode("utf-8")),
        )

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    with pytest.raises(EasyAuthClientError) as excinfo:
        _client().search_directory_users(page=2, snapshot_id="snapshot-old")

    error = excinfo.value
    assert calls == 1
    assert error.status_code == 409
    assert error.error_code == "CONFLICT"
    assert error.details == {
        "expected_snapshot_id": "snapshot-old",
        "actual_snapshot_id": "snapshot-new",
    }
    assert error.retryable is False
    assert error.transport_error is False
    assert isinstance(error.__cause__, HTTPError)
    assert error.__cause__.closed is True


def test_get_directory_user_encodes_ref(monkeypatch: Any) -> None:
    sample = _load_sample("directory/user_detail.json")
    captured = _stub_json(monkeypatch, sample)

    result = _client().get_directory_user("dt:user0123")

    assert result == sample
    _assert_bearer(captured)
    assert captured["url"] == (
        "http://easyauth:8001/api/v1/apps/my%20app/directory/users/dt%3Auser0123"
    )


def test_get_directory_user_manager(monkeypatch: Any) -> None:
    sample = _load_sample("directory/user_manager.json")
    captured = _stub_json(monkeypatch, sample)

    result = _client().get_directory_user_manager("f7c31a09e5b24f8d9a1c")

    assert result == sample
    _assert_bearer(captured)
    assert captured["url"] == (
        "http://easyauth:8001/api/v1/apps/my%20app/directory/users/"
        "f7c31a09e5b24f8d9a1c/manager"
    )


def test_list_directory_user_subordinates(monkeypatch: Any) -> None:
    sample = _load_sample("directory/user_subordinates.json")
    captured = _stub_json(monkeypatch, sample)

    result = _client().list_directory_user_subordinates("dt:manager8836")

    assert result == sample
    _assert_bearer(captured)
    assert captured["url"] == (
        "http://easyauth:8001/api/v1/apps/my%20app/directory/users/"
        "dt%3Amanager8836/subordinates"
    )


def test_list_directory_departments_without_parent(monkeypatch: Any) -> None:
    sample = _load_sample("directory/departments_list.json")
    captured = _stub_json(monkeypatch, sample)

    result = _client().list_directory_departments()

    assert result == sample
    _assert_bearer(captured)
    assert captured["url"] == "http://easyauth:8001/api/v1/apps/my%20app/directory/departments"
    assert "parent_id" not in captured["url"]


def test_list_directory_departments_with_parent(monkeypatch: Any) -> None:
    sample = _load_sample("directory/departments_list.json")
    captured = _stub_json(monkeypatch, sample)

    result = _client().list_directory_departments(parent_id="1")

    assert result == sample
    _assert_bearer(captured)
    parsed = urlparse(captured["url"])
    assert parsed.path == "/api/v1/apps/my%20app/directory/departments"
    assert parse_qs(parsed.query)["parent_id"] == ["1"]


def test_send_notification_replays_contract_sample(monkeypatch: Any) -> None:
    """请求体逐字段回放 message_create_request.json(含 deeplink_title)。"""
    request_body = _load_sample("notify/message_create_request.json")
    response = _load_sample("notify/message_create_response.json")
    captured = _stub_json(monkeypatch, response)

    result = _client().send_notification(
        recipients=request_body["recipients"],
        template=request_body["template"],
        content=request_body["content"],
        title=request_body["title"],
        deeplink_url=request_body["deeplink_url"],
        deeplink_title=request_body["deeplink_title"],
        dedup_key=request_body["dedup_key"],
        biz_tag=request_body["biz_tag"],
    )

    assert result == response
    _assert_bearer(captured)
    assert captured["method"] == "POST"
    assert captured["url"] == "http://easyauth:8001/api/v1/apps/my%20app/notify/messages"
    assert captured["body"] == request_body


def test_send_notification_minimal_body(monkeypatch: Any) -> None:
    response = _load_sample("notify/message_create_response.json")
    captured = _stub_json(monkeypatch, response)

    _ = _client().send_notification(
        recipients=["dt:user0123"],
        template=NOTIFY_TEMPLATE_TEXT,
        content="hello",
    )

    _assert_bearer(captured)
    assert captured["body"] == {
        "recipients": ["dt:user0123"],
        "template": "text",
        "content": "hello",
    }
    for optional in ("title", "deeplink_url", "deeplink_title", "dedup_key", "biz_tag"):
        assert optional not in captured["body"]


def test_get_notification(monkeypatch: Any) -> None:
    sample = _load_sample("notify/message_status.json")
    captured = _stub_json(monkeypatch, sample)
    message_id = sample["message_id"]

    result = _client().get_notification(message_id)

    assert result == sample
    _assert_bearer(captured)
    assert captured["url"] == (
        f"http://easyauth:8001/api/v1/apps/my%20app/notify/messages/{message_id}"
    )
    assert captured["method"] == "GET"
