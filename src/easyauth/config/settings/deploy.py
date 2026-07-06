"""公网反代部署 settings(iam.jiefakj.com)。

沿用 base 的开发级便利(DEBUG=1 → SQLite、runserver 服务静态资源), 但补上反向代理
下的 TLS 识别头。base 只在 `not DEBUG` 分支设 SECURE_PROXY_SSL_HEADER, 因此 DEBUG 模式
经 frpc/nginx(TLS 终止在代理, 到容器是 http)访问时 is_secure() 恒为 False,
/auth/login/ 的 canonical 比对会 302 死循环。这里显式补上。
"""

from .base import *  # noqa: F403

# frpc 已注入 x-forwarded-proto=https; 让 Django 据此识别 https 请求。
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
