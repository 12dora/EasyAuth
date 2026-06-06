from __future__ import annotations

import hmac
from hashlib import sha256
from typing import Final

from easyauth.integrations.dingtalk.signature import is_valid_callback_signature

CALLBACK_KEY: Final = "unit-callback-key"
TIMESTAMP: Final = "1764986400000"
NOW_MS: Final = 1764986400000
BODY: Final = b'{"process_instance_id":"proc-unit","status":"approved"}'


def test_dingtalk_signature_accepts_matching_hmac() -> None:
    # Given: 回调原始 body 与时间戳使用共享密钥签名。
    signature = hmac.new(
        CALLBACK_KEY.encode(),
        TIMESTAMP.encode() + b"." + BODY,
        sha256,
    ).hexdigest()

    # When: 验证回调签名。
    is_valid = is_valid_callback_signature(
        secret=CALLBACK_KEY,
        timestamp=TIMESTAMP,
        body=BODY,
        signature=signature,
        now_ms=NOW_MS,
    )

    # Then: 匹配 HMAC 被接受。
    assert is_valid is True


def test_dingtalk_signature_rejects_mismatched_hmac() -> None:
    # Given: 回调签名不是该 body 的 HMAC。
    signature = hmac.new(CALLBACK_KEY.encode(), TIMESTAMP.encode() + b".{}", sha256).hexdigest()

    # When: 验证回调签名。
    is_valid = is_valid_callback_signature(
        secret=CALLBACK_KEY,
        timestamp=TIMESTAMP,
        body=BODY,
        signature=signature,
        now_ms=NOW_MS,
    )

    # Then: 不匹配 HMAC 被拒绝。
    assert is_valid is False


def test_dingtalk_signature_rejects_expired_timestamp() -> None:
    # Given: 回调使用超过允许窗口的旧时间戳签名。
    timestamp = str(NOW_MS - 300_001)
    signature = hmac.new(
        CALLBACK_KEY.encode(),
        timestamp.encode() + b"." + BODY,
        sha256,
    ).hexdigest()

    # When: 验证回调签名。
    is_valid = is_valid_callback_signature(
        secret=CALLBACK_KEY,
        timestamp=timestamp,
        body=BODY,
        signature=signature,
        now_ms=NOW_MS,
    )

    # Then: 即使 HMAC 匹配, 旧时间戳也被拒绝。
    assert is_valid is False


def test_dingtalk_signature_rejects_future_timestamp() -> None:
    # Given: 回调使用超过允许窗口的未来时间戳签名。
    timestamp = str(NOW_MS + 300_001)
    signature = hmac.new(
        CALLBACK_KEY.encode(),
        timestamp.encode() + b"." + BODY,
        sha256,
    ).hexdigest()

    # When: 验证回调签名。
    is_valid = is_valid_callback_signature(
        secret=CALLBACK_KEY,
        timestamp=timestamp,
        body=BODY,
        signature=signature,
        now_ms=NOW_MS,
    )

    # Then: 即使 HMAC 匹配, 未来时间戳也被拒绝。
    assert is_valid is False
