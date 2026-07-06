from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Self

import pytest
from easyauth_app_sdk import (
    EasyAuthAppClient,
    WebhookVerificationError,
    verify_webhook,
)
from easyauth_app_sdk import client as client_module

SECRET = "whsec_test"  # noqa: S105 - 测试用密钥。


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
    return EasyAuthAppClient(base_url="http://easyauth:8001", app_key="etrade", token="eat_x")


def test_create_approval_posts_payload_and_returns_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse(
            json.dumps({"instance_id": "uuid-1", "status": "submitted"}).encode("utf-8")
        )

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    result = _client().create_approval(
        template_key="expense",
        originator_user_id="ak-user-1",
        form={"金额": "1000"},
        biz_key="order-42",
    )

    assert result == {"instance_id": "uuid-1", "status": "submitted"}
    assert captured["url"] == "http://easyauth:8001/api/v1/apps/etrade/approval-instances"
    assert captured["method"] == "POST"
    assert captured["body"] == {
        "template_key": "expense",
        "originator_user_id": "ak-user-1",
        "form": {"金额": "1000"},
        "biz_key": "order-42",
    }


def test_get_approval_encodes_instance_id(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_urlopen(request: Any, timeout: float) -> _FakeResponse:  # noqa: ARG001
        captured["url"] = request.full_url
        return _FakeResponse(json.dumps({"status": "approved"}).encode("utf-8"))

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)

    result = _client().get_approval("uuid/1")

    assert result == {"status": "approved"}
    assert captured["url"] == (
        "http://easyauth:8001/api/v1/apps/etrade/approval-instances/uuid%2F1"
    )


def _signed_headers(body: bytes, *, timestamp: int | None = None) -> dict[str, str]:
    ts = str(timestamp if timestamp is not None else int(time.time()))
    signature = hmac.new(
        SECRET.encode("utf-8"),
        ts.encode("utf-8") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-EasyAuth-Event": "approval.completed",
        "X-EasyAuth-Delivery": "delivery-1",
        "X-EasyAuth-Timestamp": ts,
        "X-EasyAuth-Signature": signature,
    }


def test_verify_webhook_roundtrip() -> None:
    body = json.dumps({"biz_key": "order-42", "status": "approved"}).encode("utf-8")

    event = verify_webhook(secret=SECRET, headers=_signed_headers(body), raw_body=body)

    assert event.event_type == "approval.completed"
    assert event.delivery_id == "delivery-1"
    assert event.payload == {"biz_key": "order-42", "status": "approved"}


def test_verify_webhook_accepts_lowercase_header_names() -> None:
    body = b"{}"
    headers = {key.lower(): value for key, value in _signed_headers(body).items()}

    event = verify_webhook(secret=SECRET, headers=headers, raw_body=body)

    assert event.event_type == "approval.completed"


def test_verify_webhook_rejects_bad_signature() -> None:
    body = b"{}"
    headers = _signed_headers(body)
    headers["X-EasyAuth-Signature"] = "0" * 64

    with pytest.raises(WebhookVerificationError):
        verify_webhook(secret=SECRET, headers=headers, raw_body=body)


def test_verify_webhook_rejects_stale_timestamp() -> None:
    body = b"{}"
    headers = _signed_headers(body, timestamp=int(time.time()) - 3600)

    with pytest.raises(WebhookVerificationError):
        verify_webhook(secret=SECRET, headers=headers, raw_body=body)


def test_verify_webhook_rejects_tampered_body() -> None:
    body = b'{"amount": 100}'
    headers = _signed_headers(body)

    with pytest.raises(WebhookVerificationError):
        verify_webhook(secret=SECRET, headers=headers, raw_body=b'{"amount": 999}')


def test_verify_webhook_rejects_missing_headers() -> None:
    with pytest.raises(WebhookVerificationError):
        verify_webhook(secret=SECRET, headers={}, raw_body=b"{}")
