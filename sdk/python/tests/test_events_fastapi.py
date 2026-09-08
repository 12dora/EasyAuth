from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

pytest.importorskip("fastapi", reason="fastapi 是可选集成 extra, 未安装时跳过。")
pytest.importorskip("starlette", reason="TestClient 依赖 starlette。")

from easyauth_app_sdk import EventCallbacks, WebhookEvent, easyauth_events_router
from easyauth_app_sdk.events import DEFAULT_EVENTS_PATH, GRANT_CHANGED_EVENT
from fastapi import FastAPI
from fastapi.testclient import TestClient

SECRET = "whsec_events_router"  # noqa: S105 - 测试用密钥。


def _signed_headers(body: bytes, *, event_type: str) -> dict[str, str]:
    ts = str(int(time.time()))
    signature = hmac.new(
        SECRET.encode("utf-8"),
        ts.encode("utf-8") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-EasyAuth-Event": event_type,
        "X-EasyAuth-Delivery": "delivery-events-router-1",
        "X-EasyAuth-Timestamp": ts,
        "X-EasyAuth-Signature": signature,
    }


def _client(callbacks: EventCallbacks | None = None) -> tuple[TestClient, list[str]]:
    seen: list[str] = []

    def on_grant_changed(event: WebhookEvent) -> None:
        seen.append(event.payload["user_id"])

    api = FastAPI()
    api.include_router(
        easyauth_events_router(
            lambda: SECRET,
            callbacks or EventCallbacks(on_grant_changed=on_grant_changed),
        )
    )
    return TestClient(api), seen


def test_router_dispatches_grant_changed() -> None:
    body = json.dumps(
        {
            "event_type": GRANT_CHANGED_EVENT,
            "user_id": "ak-7",
            "grant_version": 1,
            "catalog_version": 1,
            "snapshot_version": "1:1:0",
        }
    ).encode("utf-8")
    client, seen = _client()

    response = client.post(
        DEFAULT_EVENTS_PATH,
        content=body,
        headers=_signed_headers(body, event_type=GRANT_CHANGED_EVENT),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert seen == ["ak-7"]


def test_router_answers_webhook_test() -> None:
    body = json.dumps({"event_type": "webhook.test"}).encode("utf-8")
    client, _seen = _client()
    response = client.post(
        DEFAULT_EVENTS_PATH,
        content=body,
        headers=_signed_headers(body, event_type="webhook.test"),
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_router_rejects_bad_signature_with_401() -> None:
    body = json.dumps({"event_type": GRANT_CHANGED_EVENT}).encode("utf-8")
    headers = _signed_headers(body, event_type=GRANT_CHANGED_EVENT)
    headers["X-EasyAuth-Signature"] = "f" * 64
    client, _seen = _client()

    response = client.post(DEFAULT_EVENTS_PATH, content=body, headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "webhook_verification_failed"


def test_router_rejects_unknown_event() -> None:
    body = json.dumps({"event_type": "lifecycle.handover.preview"}).encode("utf-8")
    client, _seen = _client()
    response = client.post(
        DEFAULT_EVENTS_PATH,
        content=body,
        headers=_signed_headers(body, event_type="lifecycle.handover.preview"),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_event"
