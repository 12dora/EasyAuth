"""工作通知 OA 色带: 应用登记色值归一化与稳定调色板。"""

from __future__ import annotations

import hashlib
import re
from typing import Final

NOTIFY_HEAD_BGCOLOR_INVALID_MESSAGE: Final = (
    "notify_head_bgcolor 须为 6 或 8 位十六进制色值(可带 #)。"
)
# EasyAuth 自身工作通知色带, 不参与下游调色板轮换。
EASYAUTH_NOTIFY_HEAD_BGCOLOR: Final = "FF1F6FEB"
# 六色 ARGB, 按 app id 哈希取模, 同一应用始终同一色带。
NOTIFY_HEAD_BGCOLOR_PALETTE: Final[tuple[str, ...]] = (
    "FF1A7F4C",
    "FFC62828",
    "FFE65100",
    "FF6A1B9A",
    "FF00838F",
    "FF3949AB",
)
_HEX_DIGITS: Final = re.compile(r"^[0-9A-Fa-f]+$")
_RGB_LENGTH: Final = 6
_ARGB_LENGTH: Final = 8


def normalize_notify_head_bgcolor(raw: str) -> str:
    """空串表示走调色板; 否则归一成 8 位大写 ARGB。非法则 ValueError。"""
    stripped = raw.strip().removeprefix("#")
    if stripped == "":
        return ""
    if not _HEX_DIGITS.fullmatch(stripped):
        raise ValueError(NOTIFY_HEAD_BGCOLOR_INVALID_MESSAGE)
    if len(stripped) == _RGB_LENGTH:
        return f"FF{stripped.upper()}"
    if len(stripped) == _ARGB_LENGTH:
        return stripped.upper()
    raise ValueError(NOTIFY_HEAD_BGCOLOR_INVALID_MESSAGE)


def palette_notify_head_bgcolor(app_id: int) -> str:
    digest = hashlib.sha256(str(app_id).encode("utf-8")).digest()
    index = digest[0] % len(NOTIFY_HEAD_BGCOLOR_PALETTE)
    return NOTIFY_HEAD_BGCOLOR_PALETTE[index]
