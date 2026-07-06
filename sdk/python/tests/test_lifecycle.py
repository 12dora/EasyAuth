from __future__ import annotations

import hashlib
import hmac
import json
import time

from easyauth_app_sdk import (
    WebhookEvent,
    lifecycle_http_response,
)

SECRET = "whsec_lifecycle"  # noqa: S105 - 测试用密钥。


def _signed_headers(
    body: bytes,
    *,
    event_type: str,
    timestamp: int | None = None,
) -> dict[str, str]:
    ts = str(timestamp if timestamp is not None else int(time.time()))
    signature = hmac.new(
        SECRET.encode("utf-8"),
        ts.encode("utf-8") + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-EasyAuth-Event": event_type,
        "X-EasyAuth-Delivery": "delivery-lifecycle-1",
        "X-EasyAuth-Timestamp": ts,
        "X-EasyAuth-Signature": signature,
    }


def _handover_body(mode: str) -> bytes:
    return json.dumps(
        {
            "task_id": "task-1:etrade",
            "kind": "offboard",
            "from_user_id": "ak-user-1",
            "to_user_id": None,
            "mode": mode,
            "policy": {"unowned_strategy": "release_to_pool"},
        }
    ).encode("utf-8")


def _respond(
    body: bytes,
    headers: dict[str, str],
    *,
    on_preview: object = None,
    on_execute: object = None,
) -> tuple[int, dict]:
    def _unexpected(event: WebhookEvent) -> dict:
        raise AssertionError(f"不应分发到该回调: {event.event_type}")

    status_code, _headers, raw = lifecycle_http_response(
        secret_provider=lambda: SECRET,
        headers=headers,
        raw_body=body,
        on_handover_preview=on_preview or _unexpected,  # type: ignore[arg-type]
        on_handover_execute=on_execute or _unexpected,  # type: ignore[arg-type]
    )
    return status_code, json.loads(raw.decode("utf-8"))


def test_dispatches_preview_event_to_preview_callback() -> None:
    body = _handover_body("preview")
    seen: list[WebhookEvent] = []

    def on_preview(event: WebhookEvent) -> dict:
        seen.append(event)
        return {"assets": [{"type": "customer", "count": 23, "label": "名下客户"}]}

    status_code, payload = _respond(
        body,
        _signed_headers(body, event_type="lifecycle.handover.preview"),
        on_preview=on_preview,
    )

    assert status_code == 200
    assert payload["assets"][0]["count"] == 23
    assert seen[0].payload["mode"] == "preview"
    assert seen[0].delivery_id == "delivery-lifecycle-1"


def test_dispatches_execute_event_to_execute_callback() -> None:
    body = _handover_body("execute")

    status_code, payload = _respond(
        body,
        _signed_headers(body, event_type="lifecycle.handover.execute"),
        on_execute=lambda event: {"summary": {"customers_transferred": 5}},  # noqa: ARG005
    )

    assert status_code == 200
    assert payload == {"summary": {"customers_transferred": 5}}


def test_webhook_test_event_returns_ok_without_callbacks() -> None:
    body = b"{}"

    status_code, payload = _respond(body, _signed_headers(body, event_type="webhook.test"))

    assert status_code == 200
    assert payload == {"ok": True}


def test_bad_signature_returns_403() -> None:
    body = _handover_body("preview")
    headers = _signed_headers(body, event_type="lifecycle.handover.preview")
    headers["X-EasyAuth-Signature"] = "0" * 64

    status_code, payload = _respond(body, headers)

    assert status_code == 403
    assert payload["error"]["code"] == "webhook_verification_failed"


def test_stale_timestamp_returns_403() -> None:
    body = _handover_body("preview")
    headers = _signed_headers(
        body,
        event_type="lifecycle.handover.preview",
        timestamp=int(time.time()) - 3600,
    )

    status_code, payload = _respond(body, headers)

    assert status_code == 403
    assert payload["error"]["code"] == "webhook_verification_failed"


def test_unknown_event_returns_422() -> None:
    body = b"{}"

    status_code, payload = _respond(body, _signed_headers(body, event_type="approval.completed"))

    assert status_code == 422
    assert payload["error"]["code"] == "unsupported_event"


def test_callback_exception_returns_500_json() -> None:
    body = _handover_body("execute")

    def on_execute(event: WebhookEvent) -> dict:  # noqa: ARG001
        raise RuntimeError("业务回调爆炸")

    status_code, payload = _respond(
        body,
        _signed_headers(body, event_type="lifecycle.handover.execute"),
        on_execute=on_execute,
    )

    assert status_code == 500
    assert payload["error"]["code"] == "handover_callback_failed"
    assert "业务回调爆炸" in payload["error"]["message"]
