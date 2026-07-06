"""EasyAuth 公共 API 客户端(标准库实现, 零依赖)。"""

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
    """以 app 凭据调用 EasyAuth: 权限查询 + 审批中心。

    base_url: EasyAuth 服务地址, 例如 ``http://host.docker.internal:8001``。
    token: 静态 app token(``eat_`` 前缀)或 OAuth2 client-credentials 换取的 Bearer token。
    """

    base_url: str
    app_key: str
    token: str
    timeout_seconds: float = 5.0

    def query_user_permissions(self, user_id: str) -> dict[str, Any]:
        """查询用户在本应用下的授权快照(groups/grants/版本号)。"""
        url = f"{self._app_base()}/users/{quote(user_id, safe='')}/permissions"
        return self._request_json(url, method="GET")

    def create_approval(
        self,
        *,
        template_key: str,
        originator_user_id: str,
        form: dict[str, str] | None = None,
        biz_key: str,
    ) -> dict[str, Any]:
        """发起一笔钉钉审批; 同 biz_key 幂等, 重复调用返回既有实例。"""
        url = f"{self._app_base()}/approval-instances"
        return self._request_json(
            url,
            method="POST",
            body={
                "template_key": template_key,
                "originator_user_id": originator_user_id,
                "form": dict(form) if form else {},
                "biz_key": biz_key,
            },
        )

    def get_approval(self, instance_id: str) -> dict[str, Any]:
        """查询审批实例状态(webhook 之外的轮询兜底)。"""
        url = f"{self._app_base()}/approval-instances/{quote(instance_id, safe='')}"
        return self._request_json(url, method="GET")

    def _app_base(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/v1/apps/{quote(self.app_key, safe='')}"

    def _request_json(
        self,
        url: str,
        *,
        method: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json", "Authorization": f"Bearer {self.token}"}
        data: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = Request(  # noqa: S310 - URL 由集成方配置。
            url,
            data=data,
            headers=headers,
            method=method,
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
