"""描述符 HTTP 端点的纯函数内核, 不绑定任何 Web 框架。"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, Final

from easyauth_app_sdk.descriptor import build_descriptor_payload

DescriptorProvider = Callable[[], Mapping[str, Any]]

JSON_CONTENT_TYPE: Final = "application/json; charset=utf-8"


def descriptor_http_response(
    provider: DescriptorProvider,
    *,
    authorization: str | None = None,
    required_token: str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """构建描述符端点响应 (status, headers, body)。

    required_token 配置后, 请求必须携带 ``Authorization: Bearer <token>``。
    provider 抛出的异常不吞掉, 由上层框架转为 500 —— 契约构建失败必须显式暴露。
    """
    headers = {"Content-Type": JSON_CONTENT_TYPE}
    if required_token and authorization != f"Bearer {required_token}":
        body = json.dumps(
            {"error": {"code": "descriptor_unauthorized", "message": "描述符访问未授权。"}},
            ensure_ascii=False,
        ).encode("utf-8")
        return 401, headers, body
    payload = build_descriptor_payload(manifest=dict(provider()))
    return 200, headers, json.dumps(payload, ensure_ascii=False).encode("utf-8")
