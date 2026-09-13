"""UserMirror.avatar_url 的安全校验与写入优先级。

Authentik 在没有钉钉照片时会把 `data:image/svg+xml;base64,...` 首字母图放进
OIDC `picture`。EasyAuth 原样镜像 Authentik 上报的头像: https / 同源路径视为
真实照片, 允许的内联图片视为生成图。真实照片优先于生成图, 不得把已有照片
降级为首字母图。登录、目录同步、Authentik 用户同步 webhook 三个写入点共用
本模块, 禁止再复制一份规则。
"""

from __future__ import annotations

from typing import Final, Literal
from urllib.parse import urlsplit

__all__ = [
    "classify_avatar_url",
    "is_safe_avatar_url",
    "preferred_avatar_url",
    "resolve_avatar_url",
    "safe_avatar_url",
]

type AvatarKind = Literal["photo", "generated", ""]

_MAX_PHOTO_URL_LENGTH: Final = 2048
_MAX_GENERATED_AVATAR_LENGTH: Final = 16384
_DATA_IMAGE_PREFIXES: Final = (
    "data:image/svg+xml;base64,",
    "data:image/png;base64,",
    "data:image/jpeg;base64,",
    "data:image/webp;base64,",
)
_BASE64_CHARS: Final = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=",
)


def classify_avatar_url(value: str) -> AvatarKind:
    """照片、生成图或缺失/不安全。"""
    length = len(value)
    if length > _MAX_GENERATED_AVATAR_LENGTH:
        return ""
    if _is_photo_avatar_url(value):
        return "photo" if length <= _MAX_PHOTO_URL_LENGTH else ""
    if _is_generated_avatar_url(value):
        return "generated"
    return ""


def is_safe_avatar_url(value: str) -> bool:
    """允许 https URL、同源路径或白名单内联图; 其余一律拒绝。"""
    return classify_avatar_url(value) != ""


def safe_avatar_url(value: str) -> str:
    """安全则原样返回, 否则空字符串, 表示头像缺失。"""
    return value if is_safe_avatar_url(value) else ""


def resolve_avatar_url(current: str, incoming: str) -> str:
    """按照片优先规则决定应落库的值; 空或不安全的 incoming 保持 current。"""
    incoming_kind = classify_avatar_url(incoming)
    if incoming_kind == "photo":
        return incoming
    if incoming_kind == "generated" and classify_avatar_url(current) != "photo":
        return incoming
    return current


def preferred_avatar_url(*candidates: str) -> str:
    """候选中优先第一张照片, 否则第一张生成图, 否则空串。"""
    generated = ""
    for candidate in candidates:
        kind = classify_avatar_url(candidate)
        if kind == "photo":
            return candidate
        if kind == "generated" and not generated:
            generated = candidate
    return generated


def _is_photo_avatar_url(value: str) -> bool:
    if "\\" in value or any(char.isspace() for char in value):
        return False
    if value.startswith("/") and not value.startswith("//"):
        return True
    parsed = urlsplit(value)
    return parsed.scheme == "https" and parsed.netloc != ""


def _is_generated_avatar_url(value: str) -> bool:
    prefix = _matching_data_image_prefix(value)
    if prefix is None:
        return False
    body = value[len(prefix) :]
    return bool(body) and all(char in _BASE64_CHARS for char in body)


def _matching_data_image_prefix(value: str) -> str | None:
    for prefix in _DATA_IMAGE_PREFIXES:
        if value.startswith(prefix):
            return prefix
    return None
