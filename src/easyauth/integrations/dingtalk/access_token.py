from __future__ import annotations

import hashlib
import math
from typing import TYPE_CHECKING, Final, Protocol

from easyauth.integrations.dingtalk.errors import DingTalkApiRequestError

if TYPE_CHECKING:
    from easyauth.integrations.dingtalk.errors import DingTalkJson

ACCESS_TOKEN_CACHE_KEY_PREFIX: Final = "easyauth:dingtalk:access-token"  # noqa: S105
# token 提前于钉钉返回的有效期刷新, 避免边界过期。
ACCESS_TOKEN_EXPIRY_MARGIN_SECONDS: Final = 120


class TokenCache(Protocol):
    def get(self, key: str) -> object: ...

    def set(self, key: str, value: object, timeout: int) -> None: ...

    def delete(self, key: str) -> object: ...


def access_token_cache_key(app_key: str, app_secret: str) -> str:
    fingerprint = hashlib.sha256(f"{app_key}\0{app_secret}".encode()).hexdigest()
    return f"{ACCESS_TOKEN_CACHE_KEY_PREFIX}:{fingerprint}"


def read_cached_access_token(
    cache_backend: TokenCache,
    cache_key: str,
    *,
    force_refresh: bool,
) -> str | None:
    """读取缓存中的 access token; force_refresh 时跳过缓存且不碰 cache.get。"""
    if force_refresh:
        return None
    cached = cache_backend.get(cache_key)
    if isinstance(cached, str) and cached:
        return cached
    return None


def validated_access_token_payload(payload: DingTalkJson) -> tuple[str, int]:
    """校验换票响应中的 accessToken 与 expireIn, 返回 (token, expire_seconds)。"""
    token = payload.get("accessToken")
    expire_in = payload.get("expireIn")
    if not isinstance(token, str) or not token:
        message = "钉钉 accessToken 响应缺少 token。"
        raise DingTalkApiRequestError(message)
    if (
        not isinstance(expire_in, (int, float))
        or isinstance(expire_in, bool)
        or not math.isfinite(expire_in)
        or expire_in <= 0
    ):
        message = "钉钉 accessToken 响应缺少有效 expireIn。"
        raise DingTalkApiRequestError(message)
    expire_seconds = int(expire_in)
    if expire_seconds <= 0:
        message = "钉钉 accessToken 响应缺少有效 expireIn。"
        raise DingTalkApiRequestError(message)
    return token, expire_seconds


def cache_access_token(
    cache_backend: TokenCache,
    cache_key: str,
    token: str,
    expire_seconds: int,
) -> None:
    """按钉钉 expireIn 扣提前刷新窗口后写入缓存。"""
    ttl = max(1, expire_seconds - ACCESS_TOKEN_EXPIRY_MARGIN_SECONDS)
    cache_backend.set(cache_key, token, timeout=ttl)
