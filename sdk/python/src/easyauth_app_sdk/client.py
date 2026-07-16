"""EasyAuth 公共 API 客户端(标准库实现, 零依赖)。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Any, Final
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from collections.abc import Sequence
    from http.client import HTTPResponse

DEFAULT_TIMEOUT_SECONDS: Final = 5.0
DEFAULT_TOTAL_TIMEOUT_SECONDS: Final = 15.0
MAX_RESPONSE_BYTES: Final = 1024 * 1024
RESPONSE_READ_CHUNK_BYTES: Final = 64 * 1024
RESPONSE_TOO_LARGE_MESSAGE: Final = "EasyAuth 响应体超过大小上限。"
READ_TOTAL_TIMEOUT_MESSAGE: Final = "EasyAuth 响应读取超过总时限。"
REDIRECT_FORBIDDEN_MESSAGE: Final = "EasyAuth 客户端默认禁止跟随重定向。"
HTTPS_REQUIRED_MESSAGE: Final = "生产环境 EasyAuth base_url 必须使用 https。"
_HTTP_REDIRECT_MIN: Final = 300
_HTTP_REDIRECT_MAX: Final = 400

# 通知模板取值(send_notification.template)。
NOTIFY_TEMPLATE_TEXT: Final = "text"
NOTIFY_TEMPLATE_MARKDOWN: Final = "markdown"
NOTIFY_TEMPLATE_ACTION_CARD: Final = "action_card"
# 钉钉 userid 引用前缀: "dt:<dingtalk_user_id>"。
DINGTALK_REF_PREFIX: Final = "dt:"


class EasyAuthClientError(RuntimeError):
    """EasyAuth API 调用失败。"""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class EasyAuthAppClient:
    """以 app 凭据调用 EasyAuth: 权限查询 + 审批中心。

    base_url: EasyAuth 服务地址, 例如 ``https://iam.example.com``。
    token: 静态 app token(``eat_`` 前缀)或 OAuth2 client-credentials 换取的 Bearer token。
    allow_insecure_http: 仅本地开发可放开 http; 默认要求 https。
    """

    base_url: str
    app_key: str
    token: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    total_timeout_seconds: float = DEFAULT_TOTAL_TIMEOUT_SECONDS
    max_response_bytes: int = MAX_RESPONSE_BYTES
    allow_insecure_http: bool = False

    def query_user_permissions(self, user_id: str) -> dict[str, Any]:
        """查询用户在本应用下的授权快照(groups/grants/版本号)。"""
        url = f"{self._app_base()}/users/{quote(user_id, safe='')}/permissions"
        return self._request_json(url, method="GET")

    def sync_manifest(
        self,
        manifest: dict[str, Any],
        *,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """推送权限 manifest 到 EasyAuth(版本单调 + content_hash 幂等)。"""
        url = f"{self._app_base()}/manifest-sync"
        body: dict[str, Any] = {"manifest": dict(manifest)}
        if base_url is not None:
            body["base_url"] = base_url
        return self._request_json(url, method="POST", body=body)

    def list_approval_templates(self) -> dict[str, Any]:
        """列出本应用可用的活跃审批模板(含平台共用模板)。"""
        url = f"{self._app_base()}/approval-templates"
        return self._request_json(url, method="GET")

    def list_approvals(
        self,
        *,
        status: str | None = None,
        biz_key: str | None = None,
        template_key: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """分页列出本应用审批实例。"""
        params: dict[str, str] = {
            "page": str(page),
            "page_size": str(page_size),
        }
        if status is not None:
            params["status"] = status
        if biz_key is not None:
            params["biz_key"] = biz_key
        if template_key is not None:
            params["template_key"] = template_key
        url = f"{self._app_base()}/approval-instances?{urlencode(params)}"
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

    # ---- directory ----

    def search_directory_users(  # noqa: PLR0913 - 查询参数与契约 §D1 一一对应
        self,
        *,
        q: str | None = None,
        department_id: str | None = None,
        manager_id: str | None = None,
        include_inactive: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """搜索/分页拉取用户目录。GET {app_base}/directory/users。

        返回 {"data": [...], "pagination": {...}}, 字段契约见公共 API 文档 §5。
        """
        params: dict[str, str] = {
            "page": str(page),
            "page_size": str(page_size),
        }
        if q is not None:
            params["q"] = q
        if department_id is not None:
            params["department_id"] = department_id
        if manager_id is not None:
            params["manager_id"] = manager_id
        if include_inactive:
            params["include_inactive"] = "true"
        url = f"{self._app_base()}/directory/users?{urlencode(params)}"
        return self._request_json(url, method="GET")

    def get_directory_user(self, user_ref: str) -> dict[str, Any]:
        """用户详情(含主管摘要)。

        user_ref 为 user_id 或 "dt:<钉钉userid>"。
        GET {app_base}/directory/users/{user_ref}
        """
        url = f"{self._app_base()}/directory/users/{quote(user_ref, safe='')}"
        return self._request_json(url, method="GET")

    def get_directory_user_manager(self, user_ref: str) -> dict[str, Any]:
        """直接主管。

        GET {app_base}/directory/users/{user_ref}/manager
        无主管时服务端返回 404 NOT_FOUND(见契约 §D3)。
        """
        url = f"{self._app_base()}/directory/users/{quote(user_ref, safe='')}/manager"
        return self._request_json(url, method="GET")

    def list_directory_user_subordinates(self, user_ref: str) -> dict[str, Any]:
        """直接下属(不分页, 全量)。GET {app_base}/directory/users/{user_ref}/subordinates"""
        url = (
            f"{self._app_base()}/directory/users/{quote(user_ref, safe='')}/subordinates"
        )
        return self._request_json(url, method="GET")

    def list_directory_departments(
        self,
        *,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        """部门列表。

        parent_id 省略 → 全量扁平列表(客户端自建树);
        传入 → 该部门直接子部门。GET {app_base}/directory/departments
        """
        if parent_id is not None:
            query = urlencode({"parent_id": parent_id})
            url = f"{self._app_base()}/directory/departments?{query}"
        else:
            url = f"{self._app_base()}/directory/departments"
        return self._request_json(url, method="GET")

    # ---- notify ----

    def send_notification(  # noqa: PLR0913 - 请求体字段与契约 §N2 一一对应
        self,
        *,
        recipients: Sequence[str],
        template: str,
        content: str,
        title: str | None = None,
        deeplink_url: str | None = None,
        deeplink_title: str | None = None,
        dedup_key: str | None = None,
        biz_tag: str | None = None,
    ) -> dict[str, Any]:
        """发送钉钉工作通知(异步受理)。POST {app_base}/notify/messages。

        recipients 元素为 user_id 或 "dt:<钉钉userid>"; template 取
        "text" | "markdown" | "action_card"。返回 {"message_id", "accepted", ...}。
        幂等: 相同 dedup_key 重复调用返回同一 message_id 且 accepted=False。
        deeplink_title 为 action_card 按钮文案; 省略时服务端缺省为「查看详情」。
        """
        url = f"{self._app_base()}/notify/messages"
        body: dict[str, Any] = {
            "recipients": list(recipients),
            "template": template,
            "content": content,
        }
        if title is not None:
            body["title"] = title
        if deeplink_url is not None:
            body["deeplink_url"] = deeplink_url
        if deeplink_title is not None:
            body["deeplink_title"] = deeplink_title
        if dedup_key is not None:
            body["dedup_key"] = dedup_key
        if biz_tag is not None:
            body["biz_tag"] = biz_tag
        return self._request_json(url, method="POST", body=body)

    def get_notification(self, message_id: str) -> dict[str, Any]:
        """查询通知投递状态(含逐收件人明细)。GET {app_base}/notify/messages/{message_id}"""
        url = f"{self._app_base()}/notify/messages/{quote(message_id, safe='')}"
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
        self._assert_secure_url(url)
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
        deadline = monotonic() + self.total_timeout_seconds
        try:
            # 带 Bearer 的请求默认不跟随重定向, 避免跨 origin 泄露 Authorization。
            with urlopen(  # noqa: S310
                request,
                timeout=min(self.timeout_seconds, max(deadline - monotonic(), 0.001)),
            ) as response:
                status = getattr(response, "status", 0)
                if _HTTP_REDIRECT_MIN <= status < _HTTP_REDIRECT_MAX:
                    raise EasyAuthClientError(
                        REDIRECT_FORBIDDEN_MESSAGE,
                        status_code=response.status,
                    )
                raw_body = _read_bounded(
                    response,
                    deadline=deadline,
                    max_bytes=self.max_response_bytes,
                )
        except HTTPError as error:
            if _HTTP_REDIRECT_MIN <= error.code < _HTTP_REDIRECT_MAX:
                raise EasyAuthClientError(
                    REDIRECT_FORBIDDEN_MESSAGE,
                    status_code=error.code,
                ) from error
            detail = _read_error_body(error, max_bytes=min(500, self.max_response_bytes))
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

    def _assert_secure_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme == "https":
            return
        if self.allow_insecure_http and parsed.scheme == "http":
            host = (parsed.hostname or "").lower()
            if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
                return
            # docker 内部主机名在本地联调中常见, 仅在显式 allow_insecure_http 时放行。
            if host and not host.replace(".", "").isdigit():
                return
        raise EasyAuthClientError(HTTPS_REQUIRED_MESSAGE)


def _read_bounded(response: HTTPResponse, *, deadline: float, max_bytes: int) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length is not None:
        try:
            length = int(content_length)
        except (TypeError, ValueError) as error:
            raise EasyAuthClientError("EasyAuth Content-Length 无效。") from error
        if length < 0 or length > max_bytes:
            raise EasyAuthClientError(RESPONSE_TOO_LARGE_MESSAGE)
    chunks: list[bytes] = []
    total = 0
    while True:
        if monotonic() >= deadline:
            raise EasyAuthClientError(READ_TOTAL_TIMEOUT_MESSAGE)
        chunk = response.read(min(RESPONSE_READ_CHUNK_BYTES, max_bytes + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise EasyAuthClientError(RESPONSE_TOO_LARGE_MESSAGE)
        chunks.append(chunk)
    return b"".join(chunks)


def _read_error_body(error: HTTPError, *, max_bytes: int) -> str:
    try:
        raw = error.read(max_bytes + 1)
    except OSError:
        return ""
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
    return raw.decode("utf-8", errors="replace")
