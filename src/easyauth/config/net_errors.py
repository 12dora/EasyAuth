"""URL/主机校验共享异常: DNS 解析与策略层共用。"""

from __future__ import annotations

BLOCKED_HOST_MESSAGE = "目标主机解析到被禁止的内网/环回/保留地址。"
UNRESOLVABLE_HOST_MESSAGE = "目标主机无法解析。"

__all__ = (
    "BLOCKED_HOST_MESSAGE",
    "UNRESOLVABLE_HOST_MESSAGE",
    "BlockedHostError",
)


class BlockedHostError(ValueError):
    def __init__(self, message: str = BLOCKED_HOST_MESSAGE) -> None:
        super().__init__(message)
