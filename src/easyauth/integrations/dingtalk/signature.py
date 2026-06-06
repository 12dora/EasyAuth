from __future__ import annotations

import hmac
from hashlib import sha256
from time import time
from typing import Final

CALLBACK_TIMESTAMP_WINDOW_MS: Final = 5 * 60 * 1000


def is_valid_callback_signature(
    *,
    secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
    now_ms: int | None = None,
) -> bool:
    if secret == "" or timestamp == "" or signature == "":
        return False
    parsed_timestamp = _parse_timestamp_ms(timestamp)
    if parsed_timestamp is None:
        return False
    current_timestamp_ms = now_ms if now_ms is not None else _current_timestamp_ms()
    if abs(current_timestamp_ms - parsed_timestamp) > CALLBACK_TIMESTAMP_WINDOW_MS:
        return False
    expected = hmac.new(
        secret.encode(),
        timestamp.encode() + b"." + body,
        sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _parse_timestamp_ms(timestamp: str) -> int | None:
    if not timestamp.isdecimal():
        return None
    return int(timestamp)


def _current_timestamp_ms() -> int:
    return int(time() * 1000)
