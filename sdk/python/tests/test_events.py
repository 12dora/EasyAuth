from __future__ import annotations

import hashlib
import hmac
import json
import time

from easyauth_app_sdk import (
    CATALOG_CHANGED_EVENT,
    GRANT_CHANGED_EVENT,
    EventCallbacks,
    WebhookEvent,
    events_http_response,
)
from easyauth_app_sdk.events import CALLBACK_FAILED_MESSAGE

SECRET = "whsec_events"  # noqa: S105 - 测试用密钥。


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
        "X-EasyAuth-Delivery": "delivery-events-1",
        "X-EasyAuth-Timestamp": ts,
        "X-EasyAuth-Signature": signature,
    }


def _respond(
    body: bytes,
    headers: dict[str, str],
    *,
    callbacks: EventCallbacks | None = None,
    signature_failure_status: int = 401,
) -> tuple[int, dict[str, str], dict]:
    status_code, resp_headers, raw = events_http_response(
        secret_provider=lambda: SECRET,
        headers=headers,
        raw_body=body,
        callbacks=callbacks or EventCallbacks(),
        signature_failure_status=signature_failure_status,
    )
    return status_code, resp_headers, json.loads(raw.decode("utf-8"))


def test_dispatches_grant_changed() -> None:
    body = json.dumps(
        {
            "event_type": GRANT_CHANGED_EVENT,
            "app_key": "easylearning",
            "user_id": "ak-user-1",
            "grant_version": 3,
            "catalog_version": 2,
            "snapshot_version": "3:2:abc",
            "changed_at": "2026-09-08T02:00:00+00:00",
        }
    ).encode("utf-8")
    seen: list[WebhookEvent] = []

    def on_grant_changed(event: WebhookEvent) -> None:
        seen.append(event)

    status_code, _headers, payload = _respond(
        body,
        _signed_headers(body, event_type=GRANT_CHANGED_EVENT),
        callbacks=EventCallbacks(on_grant_changed=on_grant_changed),
    )

    assert status_code == 200
    assert payload == {"ok": True}
    assert seen[0].payload["user_id"] == "ak-user-1"
    assert seen[0].payload["snapshot_version"] == "3:2:abc"


def test_dispatches_catalog_changed() -> None:
    body = json.dumps(
        {
            "event_type": CATALOG_CHANGED_EVENT,
            "app_key": "easylearning",
            "catalog_version": 9,
            "changed_at": "2026-09-08T02:00:00+00:00",
        }
    ).encode("utf-8")
    seen: list[WebhookEvent] = []

    def on_catalog_changed(event: WebhookEvent) -> None:
        seen.append(event)

    status_code, _headers, payload = _respond(
        body,
        _signed_headers(body, event_type=CATALOG_CHANGED_EVENT),
        callbacks=EventCallbacks(on_catalog_changed=on_catalog_changed),
    )

    assert status_code == 200
    assert payload == {"ok": True}
    assert seen[0].payload["catalog_version"] == 9


def test_optional_callbacks_still_ack() -> None:
    body = json.dumps({"event_type": GRANT_CHANGED_EVENT, "app_key": "x"}).encode("utf-8")
    status_code, _headers, payload = _respond(
        body,
        _signed_headers(body, event_type=GRANT_CHANGED_EVENT),
    )
    assert status_code == 200
    assert payload == {"ok": True}


def test_webhook_test_short_circuits_after_event_type_match() -> None:
    body = json.dumps({"event_type": "webhook.test"}).encode("utf-8")
    status_code, _headers, payload = _respond(
        body,
        _signed_headers(body, event_type="webhook.test"),
        callbacks=EventCallbacks(on_grant_changed=lambda _event: None),
    )
    assert status_code == 200
    assert payload == {"ok": True}


def test_event_type_mismatch_is_422_before_test_shortcut() -> None:
    body = json.dumps({"event_type": GRANT_CHANGED_EVENT}).encode("utf-8")
    status_code, _headers, payload = _respond(
        body,
        _signed_headers(body, event_type="webhook.test"),
    )
    assert status_code == 422
    assert payload["error"]["code"] == "event_type_mismatch"


def test_unknown_event_is_422() -> None:
    body = json.dumps({"event_type": "approval.completed"}).encode("utf-8")
    status_code, _headers, payload = _respond(
        body,
        _signed_headers(body, event_type="approval.completed"),
    )
    assert status_code == 422
    assert payload["error"]["code"] == "unsupported_event"


def test_bad_signature_is_401_by_default() -> None:
    body = json.dumps({"event_type": GRANT_CHANGED_EVENT}).encode("utf-8")
    headers = _signed_headers(body, event_type=GRANT_CHANGED_EVENT)
    headers["X-EasyAuth-Signature"] = "f" * 64
    status_code, _headers, payload = _respond(body, headers)
    assert status_code == 401
    assert payload["error"]["code"] == "webhook_verification_failed"


def test_callback_exception_is_500_without_leaking_details() -> None:
    body = json.dumps({"event_type": GRANT_CHANGED_EVENT}).encode("utf-8")

    def boom(_event: WebhookEvent) -> None:
        message = "internal secret"
        raise RuntimeError(message)

    status_code, _headers, payload = _respond(
        body,
        _signed_headers(body, event_type=GRANT_CHANGED_EVENT),
        callbacks=EventCallbacks(on_grant_changed=boom),
    )
    assert status_code == 500
    assert payload["error"]["code"] == "event_callback_failed"
    assert payload["error"]["message"] == CALLBACK_FAILED_MESSAGE
    assert "internal secret" not in json.dumps(payload)
