from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from http import HTTPStatus
from json import JSONDecodeError, dumps, loads
from time import monotonic
from typing import TYPE_CHECKING, Final, Self, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.cache import cache

from easyauth.applications.integration_settings import dingtalk_runtime_config

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import TracebackType

# 默认走钉钉新版 v1.0 API(api.dingtalk.com); 审批等能力均有新版。
# 例外: 工作通知仅有旧版 oapi topapi(asyncsend_v2 / getsendprogress / getsendresult),
# 官方无 api.dingtalk.com 新版替代——见 docs/design/platform-directory-notify/
# 04-钉钉工作通知调研结论.md §1。oapi 例外范围仅限本文件三个工作通知方法。
DINGTALK_API_BASE_URL: Final = "https://api.dingtalk.com"
DINGTALK_OAPI_BASE_URL: Final = "https://oapi.dingtalk.com"
ACCESS_TOKEN_CACHE_KEY_PREFIX: Final = "easyauth:dingtalk:access-token"  # noqa: S105
# token 提前于钉钉返回的有效期刷新, 避免边界过期。
ACCESS_TOKEN_EXPIRY_MARGIN_SECONDS: Final = 120
DINGTALK_NOT_CONFIGURED_MESSAGE: Final = "钉钉集成凭证未配置。"
MAX_JSON_RESPONSE_BYTES: Final = 1024 * 1024
MAX_ERROR_RESPONSE_BYTES: Final = 4096
OAPI_ASYNC_SEND_PATH: Final = "/topapi/message/corpconversation/asyncsend_v2"
OAPI_GET_SEND_PROGRESS_PATH: Final = "/topapi/message/corpconversation/getsendprogress"
OAPI_GET_SEND_RESULT_PATH: Final = "/topapi/message/corpconversation/getsendresult"
# 官方 userid_list 上限, 同时保住 getsendresult 回执能力(第 4 篇 §1.1 / §2.2)。
WORK_NOTIFICATION_MAX_USERIDS: Final = 100

type DingTalkJson = dict[str, object]


class _ReadableResponse:
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def read(self, _amount: int = -1) -> bytes: ...


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

    def get_access_token(
        self,
        *,
        force_refresh: bool = False,
        _deadline: float | None = None,
    ) -> str:
        cache_key = _access_token_cache_key(self._app_key, self._app_secret)
        cached = None if force_refresh else cast("object", cache.get(cache_key))
        if isinstance(cached, str) and cached:
            return cached
        payload = self._request_json(
            "POST",
            "/v1.0/oauth2/accessToken",
            body={"appKey": self._app_key, "appSecret": self._app_secret},
            authenticated=False,
            _deadline=_deadline,
        )
        token = payload.get("accessToken")
        expire_in = payload.get("expireIn")
        if not isinstance(token, str) or not token:
            message = "钉钉 accessToken 响应缺少 token。"
            raise DingTalkApiRequestError(message)
        if (
            not isinstance(expire_in, (int, float))
            or isinstance(expire_in, bool)
            or not math.isfinite(expire_in)
            or expire_in <= 0
        ):
            message = "钉钉 accessToken 响应缺少有效 expireIn。"
            raise DingTalkApiRequestError(message)
        expire_seconds = int(expire_in)
        if expire_seconds <= 0:
            message = "钉钉 accessToken 响应缺少有效 expireIn。"
            raise DingTalkApiRequestError(message)
        ttl = max(1, expire_seconds - ACCESS_TOKEN_EXPIRY_MARGIN_SECONDS)
        cache.set(cache_key, token, timeout=ttl)
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

    def send_work_notification(
        self,
        *,
        agent_id: int | str,
        userid_list: Sequence[str],
        msg: DingTalkJson,
    ) -> str:
        """发送工作通知(旧版 oapi asyncsend_v2)。返回 task_id 字符串。

        oapi 例外说明见模块顶部注释与第 4 篇 §1。
        """
        if not userid_list:
            message = "工作通知 userid_list 不能为空。"
            raise DingTalkApiRequestError(message)
        if len(userid_list) > WORK_NOTIFICATION_MAX_USERIDS:
            message = (
                f"工作通知 userid_list 不得超过 {WORK_NOTIFICATION_MAX_USERIDS} 个。"
            )
            raise DingTalkApiRequestError(message)
        payload = self._request_oapi_json(
            OAPI_ASYNC_SEND_PATH,
            body={
                "agent_id": agent_id,
                "userid_list": ",".join(userid_list),
                "msg": msg,
            },
        )
        task_id = payload.get("task_id")
        if isinstance(task_id, bool) or not isinstance(task_id, (int, str)):
            message = "钉钉工作通知响应缺少 task_id。"
            raise DingTalkApiRequestError(message)
        return str(task_id)

    def get_send_progress(self, *, agent_id: int | str, task_id: int | str) -> DingTalkJson:
        """查询工作通知发送进度(旧版 oapi getsendprogress)。"""
        payload = self._request_oapi_json(
            OAPI_GET_SEND_PROGRESS_PATH,
            body={"agent_id": agent_id, "task_id": task_id},
        )
        progress = payload.get("progress")
        if not isinstance(progress, dict):
            message = "钉钉发送进度响应缺少 progress。"
            raise DingTalkApiRequestError(message)
        return cast("DingTalkJson", progress)

    def get_send_result(self, *, agent_id: int | str, task_id: int | str) -> DingTalkJson:
        """查询工作通知发送结果(旧版 oapi getsendresult)。"""
        payload = self._request_oapi_json(
            OAPI_GET_SEND_RESULT_PATH,
            body={"agent_id": agent_id, "task_id": task_id},
        )
        send_result = payload.get("send_result")
        if not isinstance(send_result, dict):
            message = "钉钉发送结果响应缺少 send_result。"
            raise DingTalkApiRequestError(message)
        return cast("DingTalkJson", send_result)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: DingTalkJson | None = None,
        query: dict[str, str] | None = None,
        authenticated: bool = True,
        _deadline: float | None = None,
    ) -> DingTalkJson:
        deadline = monotonic() + self._timeout_seconds if _deadline is None else _deadline
        url = f"{DINGTALK_API_BASE_URL}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["x-acs-dingtalk-access-token"] = self.get_access_token(_deadline=deadline)
        return self._execute_json_request(
            method,
            url,
            headers=headers,
            body=body,
            deadline=deadline,
        )

    def _request_oapi_json(
        self,
        path: str,
        *,
        body: DingTalkJson,
        _deadline: float | None = None,
    ) -> DingTalkJson:
        # 旧版 oapi: access_token 走查询参数(第 4 篇 §1), 不走 x-acs 头。
        deadline = monotonic() + self._timeout_seconds if _deadline is None else _deadline
        token = self.get_access_token(_deadline=deadline)
        url = f"{DINGTALK_OAPI_BASE_URL}{path}?{urlencode({'access_token': token})}"
        headers = {"Content-Type": "application/json"}
        payload = self._execute_json_request(
            "POST",
            url,
            headers=headers,
            body=body,
            deadline=deadline,
        )
        errcode = payload.get("errcode")
        if errcode is None:
            return payload
        if isinstance(errcode, bool) or not isinstance(errcode, (int, float)):
            message = "钉钉 oapi 响应 errcode 非法。"
            raise DingTalkApiRequestError(message)
        if int(errcode) != 0:
            errmsg = payload.get("errmsg")
            detail = errmsg if isinstance(errmsg, str) and errmsg else f"errcode={int(errcode)}"
            message = f"钉钉 oapi 业务错误: {detail}"
            raise DingTalkApiRequestError(message, status_code=int(errcode))
        return payload

    def _execute_json_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: DingTalkJson | None,
        deadline: float,
    ) -> DingTalkJson:
        data = dumps(body).encode("utf-8") if body is not None else None
        request = Request(url, data=data, headers=headers, method=method)  # noqa: S310 - 常量 https 基址。
        try:
            remaining = _remaining_seconds(deadline)
            with cast(
                "_ReadableResponse",
                urlopen(request, timeout=remaining),  # noqa: S310
            ) as response:
                raw = response.read(MAX_JSON_RESPONSE_BYTES + 1)
            _ = _remaining_seconds(deadline)
        except HTTPError as error:
            detail = _error_detail(error)
            message = f"钉钉 API 请求失败(HTTP {error.code}): {detail}"
            raise DingTalkApiRequestError(message, status_code=error.code) from error
        except (URLError, TimeoutError) as error:
            message = "钉钉 API 暂不可用。"
            raise DingTalkApiUnavailableError(message) from error
        if len(raw) > MAX_JSON_RESPONSE_BYTES:
            message = "钉钉 API 响应超过大小限制。"
            raise DingTalkApiRequestError(message)
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
        raw = error.read(MAX_ERROR_RESPONSE_BYTES + 1).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    if error.code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
        # 凭证类错误的响应体可能包含敏感回显, 只保留状态码。
        return ""
    return raw[:500]


def invalidate_access_token(*, app_key: str, app_secret: str) -> None:
    if app_key and app_secret:
        _ = cache.delete(_access_token_cache_key(app_key, app_secret))


def _access_token_cache_key(app_key: str, app_secret: str) -> str:
    fingerprint = hashlib.sha256(f"{app_key}\0{app_secret}".encode()).hexdigest()
    return f"{ACCESS_TOKEN_CACHE_KEY_PREFIX}:{fingerprint}"


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError
    return remaining
