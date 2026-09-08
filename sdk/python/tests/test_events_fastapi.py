from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("fastapi", reason="fastapi 是可选集成 extra, 未安装时跳过。")
pytest.importorskip("starlette", reason="TestClient 依赖 starlette。")
pytest.importorskip("httpx", reason="AsyncClient 依赖 httpx。")

from easyauth_app_sdk import EventCallbacks, WebhookEvent, easyauth_events_router
from easyauth_app_sdk.events import DEFAULT_EVENTS_PATH, GRANT_CHANGED_EVENT, events_http_response
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from starlette.concurrency import run_in_threadpool as original_run_in_threadpool

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


def test_router_runs_sync_processing_via_threadpool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[object] = []

    async def tracking_run_in_threadpool(func: object, *args: object, **kwargs: object) -> object:
        seen.append(func)
        return await original_run_in_threadpool(func, *args, **kwargs)

    monkeypatch.setattr("starlette.concurrency.run_in_threadpool", tracking_run_in_threadpool)
    body = _grant_changed_body()
    client, seen_users = _client()

    response = client.post(
        DEFAULT_EVENTS_PATH,
        content=body,
        headers=_signed_headers(body, event_type=GRANT_CHANGED_EVENT),
    )

    assert response.status_code == 200
    assert seen == [events_http_response]
    assert seen_users == ["ak-7"]


def test_router_does_not_block_event_loop_during_sync_callback() -> None:
    started = threading.Event()
    release = threading.Event()

    def on_grant_changed(_event: WebhookEvent) -> None:
        started.set()
        if not release.wait(timeout=5):
            raise AssertionError("release was not signalled")

    api = FastAPI()
    api.include_router(
        easyauth_events_router(
            lambda: SECRET,
            EventCallbacks(on_grant_changed=on_grant_changed),
        )
    )
    body = _grant_changed_body()
    headers = _signed_headers(body, event_type=GRANT_CHANGED_EVENT)

    async def scenario() -> int:
        transport = ASGITransport(app=api)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            task = asyncio.create_task(
                client.post(DEFAULT_EVENTS_PATH, content=body, headers=headers)
            )
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.01)
            if not started.is_set():
                release.set()
                _ = await asyncio.wait_for(task, timeout=1)
                raise AssertionError("sync callback blocked the event loop")
            release.set()
            response = await task
            return response.status_code

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, scenario())
        try:
            status = future.result(timeout=5)
        except TimeoutError:
            release.set()
            raise AssertionError("event loop blocked by sync events callback") from None

    assert status == 200


def _grant_changed_body() -> bytes:
    return json.dumps(
        {
            "event_type": GRANT_CHANGED_EVENT,
            "user_id": "ak-7",
            "grant_version": 1,
            "catalog_version": 1,
            "snapshot_version": "1:1:0",
        }
    ).encode("utf-8")
