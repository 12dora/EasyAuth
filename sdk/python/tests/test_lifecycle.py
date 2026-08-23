from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass

import pytest
from easyauth_app_sdk import (
    HandoverBusinessError,
    LifecycleCallbacks,
    WebhookEvent,
    lifecycle_http_response,
)
from easyauth_app_sdk.lifecycle import (
    CALLBACK_FAILED_MESSAGE,
    DEFAULT_MAX_BODY_BYTES,
    HANDOVER_ITEMS_EVENT,
)
from easyauth_app_sdk.webhook import (
    REASON_INVALID_PAYLOAD,
    REASON_SIGNATURE_MISMATCH,
    REASON_TIMESTAMP_SKEW,
)

SECRET = "whsec_lifecycle"  # noqa: S105 - 测试用密钥。


@dataclass(frozen=True)
class _Callbacks:
    preview: object = None
    execute: object = None
    items: object = None


_DEFAULT_CALLBACKS = _Callbacks()


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


def _handover_body(*, mode: str, event_type: str, **extra: object) -> bytes:
    payload: dict[str, object] = {
        "event_type": event_type,
        "task_id": "task-1:etrade",
        "generation": 1,
        "kind": "offboard",
        "from_user_id": "ak-user-1",
        "mode": mode,
    }
    payload.update(extra)
    return json.dumps(payload).encode("utf-8")


def _respond(
    body: bytes,
    headers: dict[str, str],
    *,
    callbacks: _Callbacks = _DEFAULT_CALLBACKS,
    signature_failure_status: int = 403,
) -> tuple[int, dict[str, str], dict]:
    def _unexpected(event: WebhookEvent) -> dict:
        raise AssertionError(f"不应分发到该回调: {event.event_type}")

    status_code, resp_headers, raw = lifecycle_http_response(
        secret_provider=lambda: SECRET,
        headers=headers,
        raw_body=body,
        callbacks=LifecycleCallbacks(
            on_handover_preview=callbacks.preview or _unexpected,  # type: ignore[arg-type]
            on_handover_execute=callbacks.execute or _unexpected,  # type: ignore[arg-type]
            on_handover_items=callbacks.items or _unexpected,  # type: ignore[arg-type]
        ),
        signature_failure_status=signature_failure_status,
    )
    return status_code, resp_headers, json.loads(raw.decode("utf-8"))


def test_default_max_body_bytes_is_256_kib() -> None:
    assert DEFAULT_MAX_BODY_BYTES == 256 * 1024


def test_dispatches_preview_event_to_preview_callback() -> None:
    body = _handover_body(mode="preview", event_type="lifecycle.handover.preview")
    seen: list[WebhookEvent] = []

    def on_preview(event: WebhookEvent) -> dict:
        seen.append(event)
        return {
            "snapshot_token": "tok-1",
            "assets": [{"type": "customer", "count": 23, "label": "名下客户"}],
        }

    status_code, _headers, payload = _respond(
        body,
        _signed_headers(body, event_type="lifecycle.handover.preview"),
        callbacks=_Callbacks(preview=on_preview),
    )

    assert status_code == 200
    assert payload["assets"][0]["count"] == 23
    assert seen[0].payload["mode"] == "preview"
    assert seen[0].delivery_id == "delivery-lifecycle-1"


def test_dispatches_items_event_to_items_callback() -> None:
    body = _handover_body(
        mode="items",
        event_type=HANDOVER_ITEMS_EVENT,
        snapshot_token="tok-1",
        asset_type="customer",
        page=1,
        page_size=50,
        q="",
    )
    # items 请求无 mode 字段(契约 §10.4); 上面为了复用 helper 带了 mode, 覆盖掉。
    payload = json.loads(body.decode("utf-8"))
    del payload["mode"]
    body = json.dumps(payload).encode("utf-8")

    def on_items(event: WebhookEvent) -> dict:
        assert event.payload["asset_type"] == "customer"
        return {
            "items": [{"id": "c-1", "label": "客户甲", "hint": ""}],
            "page": 1,
            "page_size": 50,
            "total": 1,
        }

    status_code, _headers, response = _respond(
        body,
        _signed_headers(body, event_type=HANDOVER_ITEMS_EVENT),
        callbacks=_Callbacks(items=on_items),
    )

    assert status_code == 200
    assert response["total"] == 1
    assert response["items"][0]["id"] == "c-1"


def test_dispatches_execute_event_to_execute_callback() -> None:
    body = _handover_body(
        mode="execute",
        event_type="lifecycle.handover.execute",
        batch_id=1,
        snapshot_token="tok-1",
        assignments=[],
    )

    status_code, _headers, payload = _respond(
        body,
        _signed_headers(body, event_type="lifecycle.handover.execute"),
        callbacks=_Callbacks(
            execute=lambda event: {  # noqa: ARG005
                "summary": {
                    "customer": {
                        "transferred": 5,
                        "released": 0,
                        "skipped": 0,
                        "merged": 0,
                        "failed": 0,
                    }
                }
            },
        ),
    )

    assert status_code == 200
    assert payload["summary"]["customer"]["transferred"] == 5


def test_webhook_test_event_returns_ok_without_callbacks() -> None:
    body = json.dumps({"event_type": "webhook.test", "message": "ping"}).encode("utf-8")

    status_code, _headers, payload = _respond(
        body, _signed_headers(body, event_type="webhook.test")
    )

    assert status_code == 200
    assert payload == {"ok": True}


def test_event_type_mismatch_returns_422_before_webhook_test_short_circuit() -> None:
    # 把真实 execute body 的事件头改成 webhook.test —— 必须 422, 不得短路成功。
    body = _handover_body(mode="execute", event_type="lifecycle.handover.execute")

    status_code, _headers, payload = _respond(
        body,
        _signed_headers(body, event_type="webhook.test"),
    )

    assert status_code == 422
    assert payload["error"]["code"] == "event_type_mismatch"


def test_missing_body_event_type_returns_422() -> None:
    body = json.dumps({"message": "EasyAuth webhook 测试事件"}).encode("utf-8")

    status_code, _headers, payload = _respond(
        body,
        _signed_headers(body, event_type="webhook.test"),
    )

    assert status_code == 422
    assert payload["error"]["code"] == "event_type_mismatch"


def test_bad_signature_returns_403_with_reason() -> None:
    body = _handover_body(mode="preview", event_type="lifecycle.handover.preview")
    headers = _signed_headers(body, event_type="lifecycle.handover.preview")
    headers["X-EasyAuth-Signature"] = "0" * 64

    status_code, _headers, payload = _respond(body, headers)

    assert status_code == 403
    assert payload["error"]["code"] == "webhook_verification_failed"
    assert payload["error"]["reason"] == REASON_SIGNATURE_MISMATCH


def test_signature_failure_status_knob_returns_401() -> None:
    # EasyProject 冻结向量: 签名失败 → 401; 旋钮只影响签名/鉴权头, 不改时间戳 400。
    body = _handover_body(mode="preview", event_type="lifecycle.handover.preview")
    headers = _signed_headers(body, event_type="lifecycle.handover.preview")
    headers["X-EasyAuth-Signature"] = "0" * 64

    status_code, _headers, payload = _respond(
        body, headers, signature_failure_status=401
    )

    assert status_code == 401
    assert payload["error"]["code"] == "webhook_verification_failed"
    assert payload["error"]["reason"] == REASON_SIGNATURE_MISMATCH


def test_signature_failure_status_rejects_success_status() -> None:
    body = _handover_body(mode="preview", event_type="lifecycle.handover.preview")
    headers = _signed_headers(body, event_type="lifecycle.handover.preview")
    headers["X-EasyAuth-Signature"] = "0" * 64

    with pytest.raises(ValueError, match="只能是 401 或 403"):
        _respond(body, headers, signature_failure_status=200)


def test_stale_timestamp_returns_400_ignoring_signature_failure_status() -> None:
    body = _handover_body(mode="preview", event_type="lifecycle.handover.preview")
    headers = _signed_headers(
        body,
        event_type="lifecycle.handover.preview",
        timestamp=int(time.time()) - 3600,
    )

    status_code, _headers, payload = _respond(
        body, headers, signature_failure_status=401
    )

    assert status_code == 400
    assert payload["error"]["code"] == "webhook_timestamp_invalid"
    assert payload["error"]["reason"] == REASON_TIMESTAMP_SKEW


@pytest.mark.parametrize("body", [b"{", b"[]"])
def test_valid_signature_with_invalid_payload_returns_400(body: bytes) -> None:
    status_code, _headers, payload = _respond(
        body,
        _signed_headers(body, event_type="lifecycle.handover.preview"),
    )

    assert status_code == 400
    assert payload["error"]["code"] == "webhook_payload_invalid"
    assert payload["error"]["reason"] == REASON_INVALID_PAYLOAD


def test_unknown_event_returns_422() -> None:
    body = json.dumps({"event_type": "approval.completed"}).encode("utf-8")

    status_code, _headers, payload = _respond(
        body,
        _signed_headers(body, event_type="approval.completed"),
    )

    assert status_code == 422
    assert payload["error"]["code"] == "unsupported_event"


def test_callback_exception_returns_500_with_fixed_message(
    caplog: logging.LogCaptureFixture,
) -> None:
    body = _handover_body(mode="execute", event_type="lifecycle.handover.execute")

    def on_execute(event: WebhookEvent) -> dict:  # noqa: ARG001
        raise RuntimeError("业务回调爆炸")

    with caplog.at_level(logging.ERROR, logger="easyauth_app_sdk.lifecycle"):
        status_code, _headers, payload = _respond(
            body,
            _signed_headers(body, event_type="lifecycle.handover.execute"),
            callbacks=_Callbacks(execute=on_execute),
        )

    assert status_code == 500
    assert payload["error"]["code"] == "handover_callback_failed"
    assert payload["error"]["message"] == CALLBACK_FAILED_MESSAGE
    assert "业务回调爆炸" not in payload["error"]["message"]
    assert any("handover callback failed" in record.message for record in caplog.records)


@pytest.mark.parametrize(
    "callback_result",
    [None, ["不是对象"], {"value": object()}],
)
def test_invalid_callback_result_returns_fixed_500(
    callback_result: object,
    caplog: logging.LogCaptureFixture,
) -> None:
    body = _handover_body(mode="preview", event_type="lifecycle.handover.preview")

    with caplog.at_level(logging.ERROR, logger="easyauth_app_sdk.lifecycle"):
        status_code, _headers, payload = _respond(
            body,
            _signed_headers(body, event_type="lifecycle.handover.preview"),
            callbacks=_Callbacks(preview=lambda _event: callback_result),
        )

    assert status_code == 500
    assert payload == {
        "error": {
            "code": "handover_callback_failed",
            "message": CALLBACK_FAILED_MESSAGE,
        },
    }
    assert any(
        "non-dict result" in record.message or "callback failed" in record.message
        for record in caplog.records
    )


def test_business_error_returns_declared_status() -> None:
    body = _handover_body(
        mode="execute",
        event_type="lifecycle.handover.execute",
        snapshot_token="stale",
    )

    def on_execute(event: WebhookEvent) -> dict:  # noqa: ARG001
        raise HandoverBusinessError(412, "snapshot_stale", "快照已失效")

    status_code, _headers, payload = _respond(
        body,
        _signed_headers(body, event_type="lifecycle.handover.execute"),
        callbacks=_Callbacks(execute=on_execute),
    )

    assert status_code == 412
    assert payload["error"]["code"] == "snapshot_stale"
    assert payload["error"]["message"] == "快照已失效"


def test_business_error_retry_after_renders_header() -> None:
    body = _handover_body(mode="items", event_type=HANDOVER_ITEMS_EVENT)
    payload = json.loads(body.decode("utf-8"))
    del payload["mode"]
    body = json.dumps(payload).encode("utf-8")

    def on_items(event: WebhookEvent) -> dict:  # noqa: ARG001
        raise HandoverBusinessError(
            429, "rate_limited", "请稍后重试", retry_after=30
        )

    status_code, headers, response = _respond(
        body,
        _signed_headers(body, event_type=HANDOVER_ITEMS_EVENT),
        callbacks=_Callbacks(items=on_items),
    )

    assert status_code == 429
    assert headers.get("Retry-After") == "30"
    assert response["error"]["code"] == "rate_limited"


def test_business_error_outside_whitelist_becomes_500(
    caplog: logging.LogCaptureFixture,
) -> None:
    body = _handover_body(mode="preview", event_type="lifecycle.handover.preview")

    def on_preview(event: WebhookEvent) -> dict:  # noqa: ARG001
        raise HandoverBusinessError(418, "teapot", "不允许")

    with caplog.at_level(logging.WARNING, logger="easyauth_app_sdk.lifecycle"):
        status_code, _headers, payload = _respond(
            body,
            _signed_headers(body, event_type="lifecycle.handover.preview"),
            callbacks=_Callbacks(preview=on_preview),
        )

    assert status_code == 500
    assert payload["error"]["code"] == "handover_callback_failed"
    assert payload["error"]["message"] == CALLBACK_FAILED_MESSAGE
    assert any(
        "outside ALLOWED_BUSINESS_STATUS" in record.message for record in caplog.records
    )
