"""生命周期(离职/转岗数据交接) webhook 端点的纯函数内核, 不绑定任何 Web 框架。

EasyAuth 会向 APP 的 handover_url 发同步 POST(三事件):
``lifecycle.handover.preview`` 预演统计(不落库),
``lifecycle.handover.items`` 明细分页(不落库),
``lifecycle.handover.execute`` 真正执行交接
(幂等键为 ``(task_id, generation, batch_id)``, 重复 execute 必须安全)。
签名规范与 :mod:`easyauth_app_sdk.webhook` 完全一致。

所有 body 必须含 ``event_type`` 字段, 且与 ``X-EasyAuth-Event`` 完全一致;
该校验位于 ``webhook.test`` 短路之前, 防止篡改事件头绕过业务回调。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, Final, Protocol

from easyauth_app_sdk.webhook import (
    REASON_INVALID_PAYLOAD,
    WebhookEvent,
    WebhookVerificationError,
    verify_webhook,
)

logger = logging.getLogger(__name__)

HANDOVER_PREVIEW_EVENT: Final = "lifecycle.handover.preview"
HANDOVER_ITEMS_EVENT: Final = "lifecycle.handover.items"
HANDOVER_EXECUTE_EVENT: Final = "lifecycle.handover.execute"
WEBHOOK_TEST_EVENT: Final = "webhook.test"
DEFAULT_HANDOVER_PATH: Final = "/api/v1/easyauth/lifecycle/handover"
# 验签前默认 body 上限: 覆盖 assignments.overrides 等 v2 载荷, 防止匿名超大体拖垮下游。
DEFAULT_MAX_BODY_BYTES: Final = 256 * 1024
BODY_TOO_LARGE_CODE: Final = "request_body_too_large"
BODY_TOO_LARGE_MESSAGE: Final = "请求体超过大小上限。"
EVENT_TYPE_MISMATCH_CODE: Final = "event_type_mismatch"
EVENT_TYPE_MISMATCH_MESSAGE: Final = "body.event_type 与 X-EasyAuth-Event 不一致。"
CALLBACK_FAILED_CODE: Final = "handover_callback_failed"
CALLBACK_FAILED_MESSAGE: Final = "交接回调执行失败，请查看应用日志"
PAYLOAD_INVALID_CODE: Final = "webhook_payload_invalid"
PAYLOAD_INVALID_MESSAGE: Final = "webhook 载荷不是有效的 JSON 对象。"
ALLOWED_SIGNATURE_FAILURE_STATUS: Final = frozenset({401, 403})
# 业务回调允许表达的 HTTP 状态码白名单(契约 §10.6)。白名单外一律按 500 处理。
ALLOWED_BUSINESS_STATUS: Final = frozenset({400, 409, 412, 413, 422, 423, 429})
# 时间戳超窗等可重试类验签失败的 reason(契约 §10.6: 400 可重试, 403 不可重试)。
_TIMESTAMP_REASONS: Final = frozenset({"INVALID_TIMESTAMP", "TIMESTAMP_SKEW"})

JSON_CONTENT_TYPE: Final = "application/json; charset=utf-8"

# 运行时取 webhook 密钥(而非 import 期读配置), 便于对接热更新的密钥存储。
SecretProvider = Callable[[], str]
# 交接回调: 接收验签通过的事件, 返回响应体(dict)。
# preview 返回 {"snapshot_token", "assets": [...]}, items 返回 {"items", "page", ...},
# execute 返回 {"summary": {...}}。
HandoverCallback = Callable[[WebhookEvent], "dict[str, Any]"]


class BodyTooLargeError(Exception):
    """请求体超过安全上限。"""


class HandoverBusinessError(Exception):
    """业务回调主动表达的非 200 状态(契约 §10.6)。

    内核捕获后按 ``status_code`` 渲染错误 JSON; 仅白名单内状态码生效,
    白名单外的值按 500 处理并写 SDK 侧 warning, 避免 APP 喂进 EasyAuth
    状态机无法解释的 2xx/3xx。

    ``retry_after`` 可选: 渲染为响应头 ``Retry-After``(秒)。契约 §10.6 要求
    EasyAuth 对 429 按该头退避; 其它状态码也可带, 由发送端决定是否消费。
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retry_after = retry_after


class _RequestLike(Protocol):
    headers: Any

    def stream(self) -> Any: ...


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


def _callback_response(
    callback: HandoverCallback,
    event: WebhookEvent,
) -> tuple[int, dict[str, str], bytes]:
    try:
        result = callback(event)
        if not isinstance(result, dict):
            logger.error(
                "handover callback returned non-dict result type=%s",
                type(result).__name__,
            )
            return _error_response(500, CALLBACK_FAILED_CODE, CALLBACK_FAILED_MESSAGE)
        return _json_response(200, result)
    except HandoverBusinessError as error:
        if error.status_code not in ALLOWED_BUSINESS_STATUS:
            logger.warning(
                "HandoverBusinessError status_code=%s outside ALLOWED_BUSINESS_STATUS; "
                "degrading to 500 (code=%s)",
                error.status_code,
                error.code,
            )
            return _error_response(500, CALLBACK_FAILED_CODE, CALLBACK_FAILED_MESSAGE)
        return _error_response(
            error.status_code,
            error.code,
            error.message,
            retry_after=error.retry_after,
        )
    except Exception:
        logger.exception("handover callback failed with unexpected exception")
        return _error_response(500, CALLBACK_FAILED_CODE, CALLBACK_FAILED_MESSAGE)


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    reason: str | None = None,
    retry_after: int | None = None,
) -> tuple[int, dict[str, str], bytes]:
    error_body: dict[str, Any] = {"code": code, "message": message}
    if reason is not None:
        error_body["reason"] = reason
    status, headers, body = _json_response(status_code, {"error": error_body})
    if retry_after is not None:
        headers = {**headers, "Retry-After": str(retry_after)}
    return status, headers, body


def body_too_large_response(
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> tuple[int, dict[str, str], bytes]:
    return _error_response(
        413,
        BODY_TOO_LARGE_CODE,
        f"{BODY_TOO_LARGE_MESSAGE}(上限 {max_body_bytes} 字节)",
    )


async def read_bounded_body(
    request: _RequestLike,
    *,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> bytes:
    """在验签前有界读取请求体: 先看 Content-Length, 再流式 N+1 截断。"""
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            length = int(content_length)
        except (TypeError, ValueError) as error:
            raise BodyTooLargeError from error
        if length < 0 or length > max_body_bytes:
            raise BodyTooLargeError
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total += len(chunk)
        if total > max_body_bytes:
            raise BodyTooLargeError
        chunks.append(chunk)
    return b"".join(chunks)


def lifecycle_http_response(
    *,
    secret_provider: SecretProvider,
    headers: dict[str, str],
    raw_body: bytes,
    on_handover_preview: HandoverCallback,
    on_handover_execute: HandoverCallback,
    on_handover_items: HandoverCallback,
    signature_failure_status: int = 403,
) -> tuple[int, dict[str, str], bytes]:
    """构建生命周期 webhook 端点响应 ``(status, headers, body)``。

    验签失败: 时间戳超窗返回 400, 签名/鉴权头失败返回 ``signature_failure_status``
    (默认 403; EasyProject 等可传 401, 见契约 §10.1);
    ``event_type`` 与事件头不一致返回 422(在 ``webhook.test`` 短路之前);
    ``webhook.test`` 直接回 ``{"ok": true}``; 按事件分发到 preview/items/execute 回调;
    未知事件返回 422; ``HandoverBusinessError`` 按白名单状态码渲染;
    其它回调异常统一转 500 固定文案(不回显 ``str(error)``)。
    """
    _validate_signature_failure_status(signature_failure_status)
    try:
        event = verify_webhook(secret=secret_provider(), headers=headers, raw_body=raw_body)
    except WebhookVerificationError as error:
        return _verification_error_response(
            error,
            signature_failure_status=signature_failure_status,
        )

    # 契约 §10.1: 必须在 webhook.test 短路之前比对 body.event_type 与事件头。
    body_event_type = event.payload.get("event_type")
    if body_event_type != event.event_type:
        return _error_response(422, EVENT_TYPE_MISMATCH_CODE, EVENT_TYPE_MISMATCH_MESSAGE)

    if event.event_type == WEBHOOK_TEST_EVENT:
        return _json_response(200, {"ok": True})
    if event.event_type == HANDOVER_PREVIEW_EVENT:
        callback = on_handover_preview
    elif event.event_type == HANDOVER_ITEMS_EVENT:
        callback = on_handover_items
    elif event.event_type == HANDOVER_EXECUTE_EVENT:
        callback = on_handover_execute
    else:
        return _error_response(422, "unsupported_event", f"不支持的事件类型: {event.event_type}")
    return _callback_response(callback, event)
