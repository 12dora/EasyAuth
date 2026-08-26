# 登录/登出链路共用的 `next` 回跳目标校验。
#
# 这个判断是开放重定向的唯一防线: 只接受本站绝对路径, 拒绝 `//evil.test` 这类
# 协议相对 URL、带 scheme/netloc 的绝对 URL, 以及含反斜杠(部分浏览器会把 `\` 规范化成 `/`,
# 从而把 `/\evil.test` 当作协议相对 URL)的路径。
# 原先 views / local_admin_views / logout_state 各存一份同样的实现, 统一到此处避免三处漂移。
from __future__ import annotations

from typing import Final
from urllib.parse import urlsplit

DEFAULT_NEXT_PATH: Final = "/portal/"


def is_local_absolute_path(value: str) -> bool:
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return False
    parsed = urlsplit(value)
    return parsed.scheme == "" and parsed.netloc == ""


def safe_next_path(value: str | None, *, default: str = DEFAULT_NEXT_PATH) -> str:
    if value is not None and is_local_absolute_path(value):
        return value
    return default
