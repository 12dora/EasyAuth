from __future__ import annotations

import os

_ = os.environ.setdefault("DJANGO_DEBUG", "1")

from .base import *  # noqa: E402

DEBUG = False  # pyright: ignore[reportConstantRedefinition]
CELERY_TASK_ALWAYS_EAGER = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
# 测试保持无外部依赖: 用单进程本地内存缓存, 不连真实 Redis。
CACHES = {  # pyright: ignore[reportConstantRedefinition]
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "easyauth-test-cache",
    },
}
