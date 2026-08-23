"""仅供本仓库全栈 E2E 使用的设置入口。"""

from __future__ import annotations

import os
from typing import Final

_DEBUG_REQUIRED_MESSAGE: Final = "E2E 设置必须显式启用 DJANGO_DEBUG=1。"

# 窄门必须在 base 之前判定: base 缺 DJANGO_SECRET_KEY 会先抛 ImproperlyConfigured,
# 那样会把"未启用 DJANGO_DEBUG"这条更准确的失败原因掩盖掉。
if os.environ.get("DJANGO_DEBUG") != "1":
    raise RuntimeError(_DEBUG_REQUIRED_MESSAGE)

from .base import *  # noqa: E402,F403
