from __future__ import annotations

import os

# 测试进程允许开发默认值(SQLite、测试密钥), 但不改变用例观察到的 DEBUG 行为。
os.environ.setdefault("DJANGO_DEBUG", "1")

from .base import *

DEBUG = False
CELERY_TASK_ALWAYS_EAGER = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
# 测试保持无外部依赖: 用单进程本地内存缓存, 不连真实 Redis。
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "easyauth-test-cache",
    },
}
