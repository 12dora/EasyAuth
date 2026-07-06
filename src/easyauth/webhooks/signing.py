from __future__ import annotations

import hashlib
import hmac
from typing import Final

# §5.1 签名规范: hex(HMAC-SHA256(secret, timestamp + "." + raw_body)),
# SDK 侧 verify_webhook 与此严格对偶。
SIGNATURE_HEADER: Final = "X-EasyAuth-Signature"
TIMESTAMP_HEADER: Final = "X-EasyAuth-Timestamp"
DELIVERY_HEADER: Final = "X-EasyAuth-Delivery"
EVENT_HEADER: Final = "X-EasyAuth-Event"
TIMESTAMP_WINDOW_SECONDS: Final = 300


def sign_webhook_body(*, secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
