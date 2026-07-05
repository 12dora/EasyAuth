from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from django.core.cache import cache

if TYPE_CHECKING:
    from django.http import HttpRequest

_PREFIX = "easyauth-ratelimit"


def _key(namespace: str, identity: str | int) -> str:
    digest = hashlib.sha256(str(identity).encode("utf-8")).hexdigest()
    return f"{_PREFIX}:{namespace}:{digest}"


def rate_limit_exceeded(
    namespace: str,
    identity: str | int,
    *,
    limit: int,
    window_seconds: int,
) -> bool:
    # 固定窗口计数限流; 依赖共享缓存后端(见 CACHES)。返回 True 表示已超过阈值。
    key = _key(namespace, identity)
    if cache.add(key, 1, window_seconds):
        return limit < 1
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, window_seconds)
        return limit < 1
    return count > limit


def over_limit(namespace: str, identity: str | int, *, limit: int) -> bool:
    # 只读判定当前计数是否已达阈值(不增量), 用于在实际计费/放行前先挡住。
    count = cache.get(_key(namespace, identity), 0)
    return isinstance(count, int) and count >= limit


def consume_once(namespace: str, identity: str, *, ttl_seconds: int) -> bool:
    # 一次性消费(去重): 首次窗口内返回 True(可继续), 重复返回 False。cache.add 原子写入。
    return cache.add(_key(namespace, identity), 1, ttl_seconds)


def client_ip(request: HttpRequest) -> str:
    # 反代终止 TLS 时客户端 IP 在 X-Forwarded-For 首跳; 否则回落 REMOTE_ADDR。
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    remote = request.META.get("REMOTE_ADDR", "")
    return remote if isinstance(remote, str) else ""
