"""仅供本仓库全栈 E2E 使用的设置入口。"""

from __future__ import annotations

import os

if os.environ.get("DJANGO_DEBUG") != "1":
    raise RuntimeError("E2E 设置必须显式启用 DJANGO_DEBUG=1。")

from .base import *  # noqa: F403
