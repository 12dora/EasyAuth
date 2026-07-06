"""EasyAuth → APP 反向 webhook 验签(标准库实现, 零依赖)。

签名规范(与 EasyAuth 服务端严格对偶):
``X-EasyAuth-Signature = hex(HMAC-SHA256(secret, timestamp + "." + raw_body))``,
并拒绝 ``|now - timestamp| > 300s`` 的请求(防重放)。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

SIGNATURE_HEADER = "X-EasyAuth-Signature"
TIMESTAMP_HEADER = "X-EasyAuth-Timestamp"
DELIVERY_HEADER = "X-EasyAuth-Delivery"
EVENT_HEADER = "X-EasyAuth-Event"
TIMESTAMP_WINDOW_SECONDS = 300


class WebhookVerificationError(RuntimeError):
    """webhook 验签失败(签名不符/时间戳超窗/头缺失/载荷非法)。"""


@dataclass(frozen=True)
class WebhookEvent:
    """验签通过后的 webhook 事件。

    ``delivery_id`` 是投递幂等键(X-EasyAuth-Delivery), APP 侧应据此去重。
    """

    event_type: str
    delivery_id: str
    timestamp: int
    payload: dict[str, Any]


def verify_webhook(
    *,
    secret: str,
    headers: Mapping[str, str],
    raw_body: bytes,
    now: int | None = None,
) -> WebhookEvent:
    """验证 EasyAuth webhook 请求并返回事件; 失败抛 WebhookVerificationError。"""
    if not secret:
        raise WebhookVerificationError("webhook secret 未配置。")
    normalized = {key.lower(): value for key, value in headers.items()}
    event_type = normalized.get(EVENT_HEADER.lower(), "")
    delivery_id = normalized.get(DELIVERY_HEADER.lower(), "")
    timestamp_raw = normalized.get(TIMESTAMP_HEADER.lower(), "")
    signature = normalized.get(SIGNATURE_HEADER.lower(), "")
    if not event_type or not delivery_id or not timestamp_raw or not signature:
        raise WebhookVerificationError("webhook 请求头不完整。")
    if not timestamp_raw.isdecimal():
        raise WebhookVerificationError("webhook 时间戳无效。")
    timestamp = int(timestamp_raw)
    current = now if now is not None else int(time.time())
    if abs(current - timestamp) > TIMESTAMP_WINDOW_SECONDS:
        raise WebhookVerificationError("webhook 时间戳超出允许窗口。")
    expected = hmac.new(
        secret.encode("utf-8"),
        timestamp_raw.encode("utf-8") + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise WebhookVerificationError("webhook 签名不匹配。")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise WebhookVerificationError("webhook 载荷不是有效 JSON。") from error
    if not isinstance(payload, dict):
        raise WebhookVerificationError("webhook 载荷必须是 JSON 对象。")
    return WebhookEvent(
        event_type=event_type,
        delivery_id=delivery_id,
        timestamp=timestamp,
        payload=payload,
    )
