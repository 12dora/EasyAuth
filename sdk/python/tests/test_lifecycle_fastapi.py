from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

pytest.importorskip("fastapi", reason="fastapi 是可选集成 extra, 未安装时跳过。")
pytest.importorskip("starlette", reason="TestClient 依赖 starlette。")

from easyauth_app_sdk import WebhookEvent, easyauth_lifecycle_router
from easyauth_app_sdk.lifecycle import DEFAULT_HANDOVER_PATH
from fastapi import FastAPI
from fastapi.testclient import TestClient

SECRET = "whsec_router"  # noqa: S105 - 测试用密钥。


def _signed_headers(body: bytes, *, event_type: str) -> dict[str, str]:
    ts = str(int(time.time()))
    signature = hmac.new(
        SECRET.encode("utf-8"),
        ts.encode("utf-8") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-EasyAuth-Event": event_type,
        "X-EasyAuth-Delivery": "delivery-router-1",
        "X-EasyAuth-Timestamp": ts,
        "X-EasyAuth-Signature": signature,
    }


def _client() -> TestClient:
    def on_preview(event: WebhookEvent) -> dict:
        asset = {"type": "customer", "count": event.payload["expected"], "label": "名下客户"}
        return {"assets": [asset]}

    def on_execute(event: WebhookEvent) -> dict:
        return {"summary": {"task_id": event.payload["task_id"]}}

    api = FastAPI()
    api.include_router(easyauth_lifecycle_router(lambda: SECRET, on_preview, on_execute))
    return TestClient(api)


def test_router_dispatches_preview() -> None:
    body = json.dumps({"mode": "preview", "expected": 7}).encode("utf-8")

    response = _client().post(
        DEFAULT_HANDOVER_PATH,
        content=body,
        headers=_signed_headers(body, event_type="lifecycle.handover.preview"),
    )

    assert response.status_code == 200
    assert response.json() == {"assets": [{"type": "customer", "count": 7, "label": "名下客户"}]}


def test_router_dispatches_execute() -> None:
    body = json.dumps({"mode": "execute", "task_id": "task-9:etrade"}).encode("utf-8")

    response = _client().post(
        DEFAULT_HANDOVER_PATH,
        content=body,
        headers=_signed_headers(body, event_type="lifecycle.handover.execute"),
    )

    assert response.status_code == 200
    assert response.json() == {"summary": {"task_id": "task-9:etrade"}}


def test_router_rejects_bad_signature() -> None:
    body = b"{}"
    headers = _signed_headers(body, event_type="lifecycle.handover.preview")
    headers["X-EasyAuth-Signature"] = "f" * 64

    response = _client().post(DEFAULT_HANDOVER_PATH, content=body, headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "webhook_verification_failed"


def test_router_answers_webhook_test() -> None:
    body = b"{}"

    response = _client().post(
        DEFAULT_HANDOVER_PATH,
        content=body,
        headers=_signed_headers(body, event_type="webhook.test"),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
