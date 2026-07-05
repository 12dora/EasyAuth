from __future__ import annotations

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _clear_cache_between_tests() -> None:
    # 节流/限流计数走共享缓存(LocMemCache 在测试进程内持久); 每个用例前后清空,
    # 避免跨用例的失败计数/请求速率互相污染。
    cache.clear()
    yield
    cache.clear()
