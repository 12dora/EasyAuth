"""生命周期(离职/转岗数据交接) webhook 端点的纯函数内核, 不绑定任何 Web 框架。

EasyAuth 会向 APP 的 handover_url 发同步 POST(两阶段):
``lifecycle.handover.preview`` 预演统计(不落库), ``lifecycle.handover.execute``
真正执行交接(payload.task_id 为幂等键, 重复 execute 必须安全)。
签名规范与 :mod:`easyauth_app_sdk.webhook` 完全一致。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Final, Protocol

from easyauth_app_sdk.webhook import (
    WebhookEvent,
    WebhookVerificationError,
    verify_webhook,
)

HANDOVER_PREVIEW_EVENT: Final = "lifecycle.handover.preview"
HANDOVER_EXECUTE_EVENT: Final = "lifecycle.handover.execute"
WEBHOOK_TEST_EVENT: Final = "webhook.test"
DEFAULT_HANDOVER_PATH: Final = "/api/v1/easyauth/lifecycle/handover"
# 验签前默认 body 上限: 足够覆盖交接 payload, 防止匿名超大体拖垮下游。
DEFAULT_MAX_BODY_BYTES: Final = 64 * 1024
BODY_TOO_LARGE_CODE: Final = "request_body_too_large"
BODY_TOO_LARGE_MESSAGE: Final = "请求体超过大小上限。"

JSON_CONTENT_TYPE: Final = "application/json; charset=utf-8"

# 运行时取 webhook 密钥(而非 import 期读配置), 便于对接热更新的密钥存储。
SecretProvider = Callable[[], str]
# 交接回调: 接收验签通过的事件, 返回响应体(dict)。
# preview 返回 {"assets": [...]}, execute 返回 {"summary": {...}}。
HandoverCallback = Callable[[WebhookEvent], "dict[str, Any]"]


class BodyTooLargeError(Exception):
    """请求体超过安全上限。"""


class _RequestLike(Protocol):
    headers: Any

    def stream(self) -> Any: ...


def _json_response(status_code: int, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    headers = {"Content-Type": JSON_CONTENT_TYPE}
    return status_code, headers, json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _error_response(status_code: int, code: str, message: str) -> tuple[int, dict[str, str], bytes]:
    return _json_response(status_code, {"error": {"code": code, "message": message}})


def body_too_large_response(max_body_bytes: int = DEFAULT_MAX_BODY_BYTES) -> tuple[int, dict[str, str], bytes]:
    return _error_response(
        413,
        BODY_TOO_LARGE_CODE,
        f"{BODY_TOO_LARGE_MESSAGE}(上限 {max_body_bytes} 字节)",
    )


async def read_bounded_body(request: _RequestLike, *, max_body_bytes: int = DEFAULT_MAX_BODY_BYTES) -> bytes:
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
) -> tuple[int, dict[str, str], bytes]:
    """构建生命周期 webhook 端点响应 ``(status, headers, body)``。

    验签失败返回 403; 按 ``X-EasyAuth-Event`` 分发到 preview/execute 回调,
    ``webhook.test`` 直接回 ``{"ok": true}``, 未知事件返回 422;
    业务回调抛出的异常统一转 500 JSON(APP 只需专注写业务回调)。
    """
    try:
        event = verify_webhook(secret=secret_provider(), headers=headers, raw_body=raw_body)
    except WebhookVerificationError as error:
        return _error_response(403, "webhook_verification_failed", str(error))
    if event.event_type == WEBHOOK_TEST_EVENT:
        return _json_response(200, {"ok": True})
    if event.event_type == HANDOVER_PREVIEW_EVENT:
        callback = on_handover_preview
    elif event.event_type == HANDOVER_EXECUTE_EVENT:
        callback = on_handover_execute
    else:
        return _error_response(422, "unsupported_event", f"不支持的事件类型: {event.event_type}")
    try:
        result = callback(event)
    except Exception as error:  # noqa: BLE001 - 回调异常边界: 业务错误必须转 500 而非击穿端点。
        return _error_response(500, "handover_callback_failed", f"交接回调执行失败: {error}")
    return _json_response(200, result)
