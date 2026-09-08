"""权限传播 webhook 端点的纯函数内核, 不绑定任何 Web 框架。

EasyAuth 会向 APP 的 ``webhook.events_url`` 异步 POST:

- ``grant.changed``: 某用户在该应用的当前授权发生变化, 下游应立即拉取该用户快照;
- ``catalog.changed``: 应用权限目录版本提升, 下游应将该应用全部缓存快照标为过期。

签名规范与 :mod:`easyauth_app_sdk.webhook` 完全一致。所有 body 必须含
``event_type`` 字段, 且与 ``X-EasyAuth-Event`` 完全一致; 该校验位于
``webhook.test`` 短路之前。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, TypedDict

from easyauth_app_sdk.lifecycle import (
    WEBHOOK_TEST_EVENT,
    SecretProvider,
)
from easyauth_app_sdk.webhook import (
    REASON_INVALID_PAYLOAD,
    WebhookEvent,
    WebhookVerificationError,
    verify_webhook,
)

logger = logging.getLogger(__name__)

GRANT_CHANGED_EVENT: Final = "grant.changed"
CATALOG_CHANGED_EVENT: Final = "catalog.changed"
DEFAULT_EVENTS_PATH: Final = "/api/v1/easyauth/events"
JSON_CONTENT_TYPE: Final = "application/json; charset=utf-8"
ALLOWED_SIGNATURE_FAILURE_STATUS: Final = frozenset({401, 403})
_TIMESTAMP_REASONS: Final = frozenset({"INVALID_TIMESTAMP", "TIMESTAMP_SKEW"})
EVENT_TYPE_MISMATCH_CODE: Final = "event_type_mismatch"
EVENT_TYPE_MISMATCH_MESSAGE: Final = "body.event_type 与 X-EasyAuth-Event 不一致。"
CALLBACK_FAILED_CODE: Final = "event_callback_failed"
CALLBACK_FAILED_MESSAGE: Final = "权限事件回调执行失败, 请查看应用日志"
PAYLOAD_INVALID_CODE: Final = "webhook_payload_invalid"
PAYLOAD_INVALID_MESSAGE: Final = "webhook 载荷不是有效的 JSON 对象。"

EventCallback = Callable[[WebhookEvent], None]


class GrantChangedPayload(TypedDict):
    event_type: Literal["grant.changed"]
    app_key: str
    user_id: str
    grant_version: int
    catalog_version: int
    snapshot_version: str
    changed_at: str


class CatalogChangedPayload(TypedDict):
    event_type: Literal["catalog.changed"]
    app_key: str
    catalog_version: int
    changed_at: str


@dataclass(frozen=True)
class EventCallbacks:
    """权限传播事件回调; 两个字段均可选, 未提供时仍确认收讫。"""

    on_grant_changed: EventCallback | None = None
    on_catalog_changed: EventCallback | None = None


def events_http_response(
    *,
    secret_provider: SecretProvider,
    headers: dict[str, str],
    raw_body: bytes,
    callbacks: EventCallbacks,
    signature_failure_status: int = 401,
) -> tuple[int, dict[str, str], bytes]:
    """构建权限传播 webhook 端点响应 ``(status, headers, body)``。

    验签失败: 时间戳超窗返回 400, 签名/鉴权头失败返回 ``signature_failure_status``
    (默认 401);
    ``event_type`` 与事件头不一致返回 422(在 ``webhook.test`` 短路之前);
    ``webhook.test`` 直接回 ``{"ok": true}``; 按事件分发到可选回调后回 ``{"ok": true}``;
    未知事件返回 422; 回调异常统一转 500 固定文案。
    """
    _validate_signature_failure_status(signature_failure_status)
    try:
        event = verify_webhook(secret=secret_provider(), headers=headers, raw_body=raw_body)
    except WebhookVerificationError as error:
        return _verification_error_response(
            error,
            signature_failure_status=signature_failure_status,
        )

    body_event_type = event.payload.get("event_type")
    if body_event_type != event.event_type:
        return _error_response(422, EVENT_TYPE_MISMATCH_CODE, EVENT_TYPE_MISMATCH_MESSAGE)

    if event.event_type == WEBHOOK_TEST_EVENT:
        return _json_response(200, {"ok": True})
    if event.event_type == GRANT_CHANGED_EVENT:
        return _dispatch(callbacks.on_grant_changed, event)
    if event.event_type == CATALOG_CHANGED_EVENT:
        return _dispatch(callbacks.on_catalog_changed, event)
    return _error_response(422, "unsupported_event", f"不支持的事件类型: {event.event_type}")


def _dispatch(
    callback: EventCallback | None,
    event: WebhookEvent,
) -> tuple[int, dict[str, str], bytes]:
    if callback is None:
        return _json_response(200, {"ok": True})
    try:
        callback(event)
    except Exception:
        logger.exception("permission event callback failed with unexpected exception")
        return _error_response(500, CALLBACK_FAILED_CODE, CALLBACK_FAILED_MESSAGE)
    return _json_response(200, {"ok": True})


def _json_response(status_code: int, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    headers = {"Content-Type": JSON_CONTENT_TYPE}
    return status_code, headers, json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _validate_signature_failure_status(signature_failure_status: int) -> None:
    if signature_failure_status not in ALLOWED_SIGNATURE_FAILURE_STATUS:
        raise ValueError("signature_failure_status 只能是 401 或 403")


def _verification_error_response(
    error: WebhookVerificationError,
    *,
    signature_failure_status: int,
) -> tuple[int, dict[str, str], bytes]:
    if error.reason in _TIMESTAMP_REASONS:
        return _error_response(
            400,
            "webhook_timestamp_invalid",
            str(error),
            reason=error.reason,
        )
    if error.reason == REASON_INVALID_PAYLOAD:
        return _error_response(
            400,
            PAYLOAD_INVALID_CODE,
            PAYLOAD_INVALID_MESSAGE,
            reason=error.reason,
        )
    return _error_response(
        signature_failure_status,
        "webhook_verification_failed",
        str(error),
        reason=error.reason,
    )


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    reason: str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    error_body: dict[str, Any] = {"code": code, "message": message}
    if reason is not None:
        error_body["reason"] = reason
    return _json_response(status_code, {"error": error_body})
