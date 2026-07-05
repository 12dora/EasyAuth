"""描述符 HTTP 端点的纯函数内核, 不绑定任何 Web 框架。"""

from __future__ import annotations

import hmac
import json
from collections.abc import Callable, Mapping
from typing import Any, Final

from easyauth_app_sdk.descriptor import build_descriptor_payload

DescriptorProvider = Callable[[], Mapping[str, Any]]
# 接收 Bearer token 明文(缺失时为 None), 返回是否放行; 供集成方接入自有密钥存储。
TokenValidator = Callable[[str | None], bool]

JSON_CONTENT_TYPE: Final = "application/json; charset=utf-8"

BEARER_PREFIX: Final = "Bearer "


def bearer_token(authorization: str | None) -> str | None:
    """从 Authorization 头提取 Bearer token 明文; 无或格式不符时返回 None。"""
    if authorization is None or not authorization.startswith(BEARER_PREFIX):
        return None
    token = authorization[len(BEARER_PREFIX) :].strip()
    return token or None


def descriptor_http_response(
    provider: DescriptorProvider,
    *,
    authorization: str | None = None,
    required_token: str | None = None,
    token_validator: TokenValidator | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """构建描述符端点响应 (status, headers, body)。

    鉴权二选一: ``required_token`` 为固定共享密钥; ``token_validator`` 为动态校验
    回调(集成方对接自有密钥存储, 例如数据库管理的同步密钥)。两者都未配置时端点开放。
    provider 抛出的异常不吞掉, 由上层框架转为 500 —— 契约构建失败必须显式暴露。
    """
    headers = {"Content-Type": JSON_CONTENT_TYPE}
    if token_validator is not None:
        authorized = token_validator(bearer_token(authorization))
    elif required_token:
        # 常量时间比较, 避免 == 短路泄露长期共享密钥的长度/前缀时序; 统一走 bearer_token 提取。
        provided = bearer_token(authorization)
        authorized = provided is not None and hmac.compare_digest(provided, required_token)
    else:
        authorized = True
    if not authorized:
        body = json.dumps(
            {"error": {"code": "descriptor_unauthorized", "message": "描述符访问未授权。"}},
            ensure_ascii=False,
        ).encode("utf-8")
        return 401, headers, body
    payload = build_descriptor_payload(manifest=dict(provider()))
    return 200, headers, json.dumps(payload, ensure_ascii=False).encode("utf-8")
