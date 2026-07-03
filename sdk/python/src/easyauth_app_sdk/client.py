"""EasyAuth 公共权限查询 API 客户端(标准库实现, 零依赖)。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class EasyAuthClientError(RuntimeError):
    """EasyAuth API 调用失败。"""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class EasyAuthAppClient:
    """以 app 凭据查询 EasyAuth 授权事实。

    base_url: EasyAuth 服务地址, 例如 ``http://host.docker.internal:8001``。
    token: 静态 app token(``eat_`` 前缀)或 OAuth2 client-credentials 换取的 Bearer token。
    """

    base_url: str
    app_key: str
    token: str
    timeout_seconds: float = 5.0

    def query_user_permissions(self, user_id: str) -> dict[str, Any]:
        """查询用户在本应用下的授权快照(groups/grants/版本号)。"""
        url = (
            f"{self.base_url.rstrip('/')}/api/v1/apps/{quote(self.app_key, safe='')}"
            f"/users/{quote(user_id, safe='')}/permissions"
        )
        request = Request(  # noqa: S310 - URL 由集成方配置。
            url,
            headers={"Accept": "application/json", "Authorization": f"Bearer {self.token}"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                raw_body = response.read()
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise EasyAuthClientError(
                f"EasyAuth 返回 HTTP {error.code}: {detail}", status_code=error.code
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise EasyAuthClientError(f"无法连接 EasyAuth: {error}") from error
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise EasyAuthClientError("EasyAuth 返回了无效 JSON。") from error
        if not isinstance(payload, dict):
            raise EasyAuthClientError("EasyAuth 返回格式无效。")
        return payload
