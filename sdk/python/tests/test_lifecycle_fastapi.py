from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

pytest.importorskip("fastapi", reason="fastapi 是可选集成 extra, 未安装时跳过。")
pytest.importorskip("starlette", reason="TestClient 依赖 starlette。")

from easyauth_app_sdk import WebhookEvent, easyauth_lifecycle_router
from easyauth_app_sdk.lifecycle import DEFAULT_HANDOVER_PATH, DEFAULT_MAX_BODY_BYTES
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
        return {"snapshot_token": "tok", "assets": [asset]}

    def on_execute(event: WebhookEvent) -> dict:
        return {"summary": {"task_id": event.payload["task_id"]}}

    def on_items(event: WebhookEvent) -> dict:
        return {
            "items": [{"id": "1", "label": event.payload["asset_type"], "hint": ""}],
            "page": event.payload["page"],
            "page_size": event.payload["page_size"],
            "total": 1,
        }

    api = FastAPI()
    api.include_router(
        easyauth_lifecycle_router(
            lambda: SECRET,
            on_preview,
            on_execute,
            on_items,
        )
    )
    return TestClient(api)


def test_router_dispatches_preview() -> None:
    body = json.dumps(
        {
            "event_type": "lifecycle.handover.preview",
            "mode": "preview",
            "expected": 7,
        }
    ).encode("utf-8")

    response = _client().post(
        DEFAULT_HANDOVER_PATH,
        content=body,
        headers=_signed_headers(body, event_type="lifecycle.handover.preview"),
    )

    assert response.status_code == 200
    assert response.json() == {
        "snapshot_token": "tok",
        "assets": [{"type": "customer", "count": 7, "label": "名下客户"}],
    }


def test_router_dispatches_items() -> None:
    body = json.dumps(
        {
            "event_type": "lifecycle.handover.items",
            "asset_type": "customer",
            "page": 1,
            "page_size": 50,
        }
    ).encode("utf-8")

    response = _client().post(
        DEFAULT_HANDOVER_PATH,
        content=body,
        headers=_signed_headers(body, event_type="lifecycle.handover.items"),
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["label"] == "customer"


def test_router_dispatches_execute() -> None:
    body = json.dumps(
        {
            "event_type": "lifecycle.handover.execute",
            "mode": "execute",
            "task_id": "task-9:etrade",
        }
    ).encode("utf-8")

    response = _client().post(
        DEFAULT_HANDOVER_PATH,
        content=body,
        headers=_signed_headers(body, event_type="lifecycle.handover.execute"),
    )

    assert response.status_code == 200
    assert response.json() == {"summary": {"task_id": "task-9:etrade"}}


def test_router_rejects_bad_signature() -> None:
    body = json.dumps({"event_type": "lifecycle.handover.preview"}).encode("utf-8")
    headers = _signed_headers(body, event_type="lifecycle.handover.preview")
    headers["X-EasyAuth-Signature"] = "f" * 64

    response = _client().post(DEFAULT_HANDOVER_PATH, content=body, headers=headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "webhook_verification_failed"


def test_router_answers_webhook_test() -> None:
    body = json.dumps({"event_type": "webhook.test"}).encode("utf-8")

    response = _client().post(
        DEFAULT_HANDOVER_PATH,
        content=body,
        headers=_signed_headers(body, event_type="webhook.test"),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_router_rejects_oversized_unsigned_body() -> None:
    api = FastAPI()
    api.include_router(
        easyauth_lifecycle_router(
            lambda: SECRET,
            lambda _event: {"assets": []},
            lambda _event: {"summary": {}},
            lambda _event: {"items": [], "page": 1, "page_size": 50, "total": 0},
            max_body_bytes=32,
        )
    )
    body = b"x" * 64
    response = TestClient(api).post(
        DEFAULT_HANDOVER_PATH,
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_body_too_large"


def test_router_signature_failure_status_knob() -> None:
    api = FastAPI()
    api.include_router(
        easyauth_lifecycle_router(
            lambda: SECRET,
            lambda _event: {"assets": []},
            lambda _event: {"summary": {}},
            lambda _event: {"items": [], "page": 1, "page_size": 50, "total": 0},
            signature_failure_status=401,
        )
    )
    body = json.dumps({"event_type": "lifecycle.handover.preview"}).encode("utf-8")
    headers = _signed_headers(body, event_type="lifecycle.handover.preview")
    headers["X-EasyAuth-Signature"] = "f" * 64

    response = TestClient(api).post(DEFAULT_HANDOVER_PATH, content=body, headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "webhook_verification_failed"


def test_router_rejects_invalid_signature_failure_status_at_construction() -> None:
    with pytest.raises(ValueError, match="只能是 401 或 403"):
        easyauth_lifecycle_router(
            lambda: SECRET,
            lambda _event: {"assets": []},
            lambda _event: {"summary": {}},
            lambda _event: {"items": [], "page": 1, "page_size": 50, "total": 0},
            signature_failure_status=200,
        )


def test_router_default_max_body_is_256_kib() -> None:
    assert DEFAULT_MAX_BODY_BYTES == 256 * 1024
