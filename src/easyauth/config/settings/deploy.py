"""公网反代部署 settings(iam.jiefakj.com)。

沿用 base 的开发级便利(DEBUG=1 → SQLite、runserver 服务静态资源), 但补上反向代理
下的 TLS 识别头。base 只在 `not DEBUG` 分支设 SECURE_PROXY_SSL_HEADER, 因此 DEBUG 模式
经 frpc/nginx(TLS 终止在代理, 到容器是 http)访问时 is_secure() 恒为 False,
/auth/login/ 的 canonical 比对会 302 死循环。这里显式补上。
"""

import os
from typing import Final

_E2E_WEBHOOK_FORBIDDEN_MESSAGE: Final = "部署设置禁止启用 E2E 明文 webhook 窄门。"

# 窄门必须在 base 之前判定: base 的初始化会先抛 ImproperlyConfigured,
# 那样会把"部署环境误开 E2E 明文 webhook"这条更准确的失败原因掩盖掉。
if os.environ.get("EASYAUTH_E2E_ALLOW_INSECURE_WEBHOOK_HOSTS", "").strip():
    raise RuntimeError(_E2E_WEBHOOK_FORBIDDEN_MESSAGE)

from .base import *  # noqa: E402,F403

# frpc 已注入 x-forwarded-proto=https; 让 Django 据此识别 https 请求。
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
