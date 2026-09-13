"""UserMirror.avatar_url 的安全校验。

Authentik 在没有钉钉照片时会把 `data:image/svg+xml` 首字母图放进 OIDC `picture`。
EasyAuth 必须把这类值视为缺失, 不得写入 `avatar_url`。
登录、目录同步、Authentik 用户同步 webhook 三个写入点共用本模块, 禁止再复制一份规则。
"""

from __future__ import annotations

from urllib.parse import urlsplit

__all__ = ["is_safe_avatar_url", "safe_avatar_url"]


def is_safe_avatar_url(value: str) -> bool:
    """允许 https URL 或同源路径; 空值与 data:/http:/javascript:/协议相对地址一律拒绝。"""
    if value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return True
    parsed = urlsplit(value)
    return parsed.scheme == "https" and parsed.netloc != ""


def safe_avatar_url(value: str) -> str:
    """安全则原样返回, 否则空字符串, 表示头像缺失。"""
    return value if is_safe_avatar_url(value) else ""
