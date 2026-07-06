from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from json import JSONDecodeError, dumps, loads
from typing import TYPE_CHECKING, Final, Self, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.cache import cache

from easyauth.applications.integration_settings import dingtalk_runtime_config

if TYPE_CHECKING:
    from types import TracebackType

# 直接使用钉钉新版 v1.0 API(§7 决策 2), 不接旧 topapi。
DINGTALK_API_BASE_URL: Final = "https://api.dingtalk.com"
ACCESS_TOKEN_CACHE_KEY: Final = "easyauth:dingtalk:access-token"  # noqa: S105 - 缓存键名.
# token 提前于钉钉返回的有效期刷新, 避免边界过期。
ACCESS_TOKEN_EXPIRY_MARGIN_SECONDS: Final = 120
DINGTALK_NOT_CONFIGURED_MESSAGE: Final = "钉钉集成凭证未配置。"

type DingTalkJson = dict[str, object]


class _ReadableResponse:
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def read(self) -> bytes: ...


class DingTalkApiError(RuntimeError):
    pass


class DingTalkNotConfiguredError(DingTalkApiError):
    def __init__(self) -> None:
        super().__init__(DINGTALK_NOT_CONFIGURED_MESSAGE)


class DingTalkApiUnavailableError(DingTalkApiError):
    pass


class DingTalkApiRequestError(DingTalkApiError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code: int | None = status_code


@dataclass(frozen=True, slots=True)
class DingTalkFormComponent:
    name: str
    value: str


class DingTalkApiClient:
    _app_key: str
    _app_secret: str
    _timeout_seconds: float

    def __init__(self, *, app_key: str, app_secret: str, timeout_seconds: float) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_settings(cls) -> DingTalkApiClient:
        config = dingtalk_runtime_config()
        if not config.is_configured():
            raise DingTalkNotConfiguredError
        return cls(
            app_key=config.app_key,
            app_secret=config.app_secret,
            timeout_seconds=config.timeout_seconds,
        )

    def get_access_token(self) -> str:
        cached = cast("object", cache.get(ACCESS_TOKEN_CACHE_KEY))
        if isinstance(cached, str) and cached:
            return cached
        payload = self._request_json(
            "POST",
            "/v1.0/oauth2/accessToken",
            body={"appKey": self._app_key, "appSecret": self._app_secret},
            authenticated=False,
        )
        token = payload.get("accessToken")
        expire_in = payload.get("expireIn")
        if not isinstance(token, str) or not token:
            message = "钉钉 accessToken 响应缺少 token。"
            raise DingTalkApiRequestError(message)
        ttl = 3600
        if isinstance(expire_in, (int, float)):
            expire_seconds = int(expire_in)
            if expire_seconds > ACCESS_TOKEN_EXPIRY_MARGIN_SECONDS:
                ttl = expire_seconds - ACCESS_TOKEN_EXPIRY_MARGIN_SECONDS
        cache.set(ACCESS_TOKEN_CACHE_KEY, token, timeout=ttl)
        return token

    def create_process_instance(
        self,
        *,
        process_code: str,
        originator_userid: str,
        dept_id: int = -1,
        form_components: tuple[DingTalkFormComponent, ...],
    ) -> str:
        payload = self._request_json(
            "POST",
            "/v1.0/workflow/processInstances",
            body={
                "processCode": process_code,
                "originatorUserId": originator_userid,
                "deptId": dept_id,
                "formComponentValues": [
                    {"name": component.name, "value": component.value}
                    for component in form_components
                ],
            },
        )
        instance_id = payload.get("instanceId")
        if not isinstance(instance_id, str) or not instance_id:
            message = "钉钉创建审批实例响应缺少 instanceId。"
            raise DingTalkApiRequestError(message)
        return instance_id

    def get_process_instance(self, process_instance_id: str) -> DingTalkJson:
        payload = self._request_json(
            "GET",
            "/v1.0/workflow/processInstances",
            query={"processInstanceId": process_instance_id},
        )
        result = payload.get("result")
        if not isinstance(result, dict):
            message = "钉钉查询审批实例响应缺少 result。"
            raise DingTalkApiRequestError(message)
        return cast("DingTalkJson", result)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: DingTalkJson | None = None,
        query: dict[str, str] | None = None,
        authenticated: bool = True,
    ) -> DingTalkJson:
        url = f"{DINGTALK_API_BASE_URL}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["x-acs-dingtalk-access-token"] = self.get_access_token()
        data = dumps(body).encode("utf-8") if body is not None else None
        request = Request(url, data=data, headers=headers, method=method)  # noqa: S310 - 常量 https 基址。
        try:
            with cast(
                "_ReadableResponse",
                urlopen(request, timeout=self._timeout_seconds),  # noqa: S310
            ) as response:
                raw = response.read()
        except HTTPError as error:
            detail = _error_detail(error)
            message = f"钉钉 API 请求失败(HTTP {error.code}): {detail}"
            raise DingTalkApiRequestError(message, status_code=error.code) from error
        except (URLError, TimeoutError) as error:
            message = "钉钉 API 暂不可用。"
            raise DingTalkApiUnavailableError(message) from error
        try:
            parsed = cast("object", loads(raw.decode("utf-8")))
        except (JSONDecodeError, UnicodeDecodeError) as error:
            message = "钉钉 API 响应不是有效 JSON。"
            raise DingTalkApiRequestError(message) from error
        if not isinstance(parsed, dict):
            message = "钉钉 API 响应必须是 JSON 对象。"
            raise DingTalkApiRequestError(message)
        return cast("DingTalkJson", parsed)


def _error_detail(error: HTTPError) -> str:
    try:
        raw = error.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    if error.code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
        # 凭证类错误的响应体可能包含敏感回显, 只保留状态码。
        return ""
    return raw[:500]
