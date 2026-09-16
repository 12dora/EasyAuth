from __future__ import annotations

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
from easyauth.integrations.dingtalk.access_token import (
    access_token_cache_key as _access_token_cache_key,
)
from easyauth.integrations.dingtalk.access_token import (
    cache_access_token,
    read_cached_access_token,
    validated_access_token_payload,
)
from easyauth.integrations.dingtalk.errors import (
    DingTalkApiError,
    DingTalkApiRequestError,
    DingTalkApiUnavailableError,
    DingTalkNotConfiguredError,
)
from easyauth.integrations.dingtalk.robot import (
    ROBOT_ACTION_SINGLE_TITLE,
    ROBOT_MSG_KEY_ACTION_CARD,
    ROBOT_MSG_KEY_MARKDOWN,
    ROBOT_OTO_BATCH_SEND_PATH,
    ROBOT_OTO_MAX_USERIDS,
    DingTalkRobotOtoResult,
    chunk_robot_user_ids,
    parse_robot_oto_result,
    robot_msg_key_and_param,
    validated_robot_user_ids,
)
from easyauth.integrations.dingtalk.work_notification import (
    OAPI_ASYNC_SEND_PATH,
    OAPI_GET_SEND_PROGRESS_PATH,
    OAPI_GET_SEND_RESULT_PATH,
    WORK_NOTIFICATION_MAX_USERIDS,
    DingTalkForbiddenReceipt,
    DingTalkSendProgress,
    DingTalkSendResult,
    parse_send_progress,
    parse_send_result,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import TracebackType

    from easyauth.integrations.dingtalk.errors import DingTalkJson

# 默认走钉钉新版 v1.0 API(api.dingtalk.com); 审批、服务号机器人单聊等均有新版。
# 例外: 工作通知仅有旧版 oapi topapi(asyncsend_v2 / getsendprogress / getsendresult),
# 官方无 api.dingtalk.com 新版替代——见 docs/architecture/platform-directory-notify.md
# 04-钉钉工作通知调研结论.md §1。oapi 例外范围仅限本文件三个工作通知方法。
DINGTALK_API_BASE_URL: Final = "https://api.dingtalk.com"
DINGTALK_OAPI_BASE_URL: Final = "https://oapi.dingtalk.com"
MAX_JSON_RESPONSE_BYTES: Final = 1024 * 1024
MAX_ERROR_RESPONSE_BYTES: Final = 4096

__all__ = (
    "DINGTALK_API_BASE_URL",
    "DINGTALK_OAPI_BASE_URL",
    "MAX_JSON_RESPONSE_BYTES",
    "ROBOT_MSG_KEY_ACTION_CARD",
    "ROBOT_MSG_KEY_MARKDOWN",
    "ROBOT_OTO_BATCH_SEND_PATH",
    "ROBOT_OTO_MAX_USERIDS",
    "WORK_NOTIFICATION_MAX_USERIDS",
    "DingTalkApiClient",
    "DingTalkApiError",
    "DingTalkApiRequestError",
    "DingTalkApiUnavailableError",
    "DingTalkForbiddenReceipt",
    "DingTalkFormComponent",
    "DingTalkNotConfiguredError",
    "DingTalkRobotOtoResult",
    "DingTalkSendProgress",
    "DingTalkSendResult",
    "chunk_robot_user_ids",
    "invalidate_access_token",
)


@dataclass(frozen=True, slots=True)
class DingTalkFormComponent:
    name: str
    value: str


class _ReadableResponse:
    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def read(self, _amount: int = -1) -> bytes: ...


@dataclass(frozen=True, slots=True)
class _JsonRequestOptions:
    body: DingTalkJson | None = None
    query: dict[str, str] | None = None
    authenticated: bool = True
    deadline: float | None = None


_DEFAULT_JSON_REQUEST_OPTIONS: Final = _JsonRequestOptions()


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

    @classmethod
    def from_notify_settings(cls) -> DingTalkApiClient:
        """工作通知换票: 使用运行时 notify 三元组(服务号, 未配齐则回退主应用)。"""
        config = dingtalk_runtime_config()
        notify = config.notify
        if not notify.is_configured():
            raise DingTalkNotConfiguredError
        return cls(
            app_key=notify.app_key,
            app_secret=notify.app_secret,
            timeout_seconds=config.timeout_seconds,
        )

    @property
    def app_key(self) -> str:
        return self._app_key

    def get_access_token(
        self,
        *,
        force_refresh: bool = False,
        _deadline: float | None = None,
    ) -> str:
        """新版 API 换票: POST /v1.0/oauth2/accessToken, 供 x-acs-dingtalk-access-token 使用。

        工作通知 oapi 与服务号机器人 batchSend 共用这一枚 token 与同一套缓存/超时约定。
        """
        cache_key = _access_token_cache_key(self._app_key, self._app_secret)
        cached = read_cached_access_token(cache, cache_key, force_refresh=force_refresh)
        if cached is not None:
            return cached
        payload = self._request_unauthenticated_access_token(_deadline=_deadline)
        token, expire_seconds = validated_access_token_payload(payload)
        cache_access_token(cache, cache_key, token, expire_seconds)
        return token

    def _request_unauthenticated_access_token(
        self,
        *,
        _deadline: float | None,
    ) -> DingTalkJson:
        """未认证换票: accessToken 接口本身不能再带 x-acs token。"""
        return self._request_json(
            "POST",
            "/v1.0/oauth2/accessToken",
            options=_JsonRequestOptions(
                body={"appKey": self._app_key, "appSecret": self._app_secret},
                authenticated=False,
                deadline=_deadline,
            ),
        )

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
            options=_JsonRequestOptions(
                body={
                    "processCode": process_code,
                    "originatorUserId": originator_userid,
                    "deptId": dept_id,
                    "formComponentValues": [
                        {"name": component.name, "value": component.value}
                        for component in form_components
                    ],
                },
            ),
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
            options=_JsonRequestOptions(query={"processInstanceId": process_instance_id}),
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

        oapi 例外说明见模块顶部注释。
        """
        if not userid_list:
            message = "工作通知 userid_list 不能为空。"
            raise DingTalkApiRequestError(message)
        if len(userid_list) > WORK_NOTIFICATION_MAX_USERIDS:
            message = f"工作通知 userid_list 不得超过 {WORK_NOTIFICATION_MAX_USERIDS} 个。"
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

    def get_send_progress(self, *, agent_id: int | str, task_id: int | str) -> DingTalkSendProgress:
        """查询工作通知发送进度(旧版 oapi getsendprogress)。"""
        payload = self._request_oapi_json(
            OAPI_GET_SEND_PROGRESS_PATH,
            body={"agent_id": agent_id, "task_id": task_id},
        )
        progress = payload.get("progress")
        if not isinstance(progress, dict):
            message = "钉钉发送进度响应缺少 progress。"
            raise DingTalkApiRequestError(message)
        return parse_send_progress(cast("DingTalkJson", progress))

    def get_send_result(self, *, agent_id: int | str, task_id: int | str) -> DingTalkSendResult:
        """查询工作通知发送结果(旧版 oapi getsendresult)。"""
        payload = self._request_oapi_json(
            OAPI_GET_SEND_RESULT_PATH,
            body={"agent_id": agent_id, "task_id": task_id},
        )
        send_result = payload.get("send_result")
        if not isinstance(send_result, dict):
            message = "钉钉发送结果响应缺少 send_result。"
            raise DingTalkApiRequestError(message)
        return parse_send_result(cast("DingTalkJson", send_result))

    def send_robot_oto_messages(
        self,
        *,
        robot_code: str,
        user_ids: Sequence[str],
        title: str,
        text: str,
        single_url: str = "",
    ) -> tuple[DingTalkRobotOtoResult, ...]:
        """服务号机器人一对一消息: 新版 batchSend, userIds 按 ≤20 分批。

        走 `_request_json`(x-acs token、超时 deadline、HTTPError/URLError 映射)与其它新版
        API 同一套重试/退避入口; 本方法不在客户端内静默吞失败。
        """
        if not robot_code.strip():
            message = "机器人 robotCode 不能为空。"
            raise DingTalkApiRequestError(message)
        normalized = validated_robot_user_ids(user_ids)
        msg_key, msg_param = robot_msg_key_and_param(
            title=title,
            text=text,
            single_url=single_url,
            single_title=ROBOT_ACTION_SINGLE_TITLE,
        )
        return tuple(
            self._send_robot_oto_batch(
                robot_code=robot_code.strip(),
                user_ids=chunk,
                msg_key=msg_key,
                msg_param=msg_param,
            )
            for chunk in chunk_robot_user_ids(normalized)
        )

    def _send_robot_oto_batch(
        self,
        *,
        robot_code: str,
        user_ids: tuple[str, ...],
        msg_key: str,
        msg_param: str,
    ) -> DingTalkRobotOtoResult:
        if len(user_ids) > ROBOT_OTO_MAX_USERIDS:
            message = f"机器人单聊 userIds 不得超过 {ROBOT_OTO_MAX_USERIDS} 个。"
            raise DingTalkApiRequestError(message)
        payload = self._request_json(
            "POST",
            ROBOT_OTO_BATCH_SEND_PATH,
            options=_JsonRequestOptions(
                body={
                    "robotCode": robot_code,
                    "userIds": list(user_ids),
                    "msgKey": msg_key,
                    "msgParam": msg_param,
                },
            ),
        )
        return parse_robot_oto_result(payload, user_ids)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        options: _JsonRequestOptions = _DEFAULT_JSON_REQUEST_OPTIONS,
    ) -> DingTalkJson:
        deadline = (
            monotonic() + self._timeout_seconds if options.deadline is None else options.deadline
        )
        url = f"{DINGTALK_API_BASE_URL}{path}"
        if options.query:
            url = f"{url}?{urlencode(options.query)}"
        headers = {"Content-Type": "application/json"}
        if options.authenticated:
            headers["x-acs-dingtalk-access-token"] = self.get_access_token(_deadline=deadline)
        return self._execute_json_request(
            method,
            url,
            headers=headers,
            body=options.body,
            deadline=deadline,
        )

    def _request_oapi_json(
        self,
        path: str,
        *,
        body: DingTalkJson,
        _deadline: float | None = None,
    ) -> DingTalkJson:
        # 旧版 oapi: access_token 走查询参数, 不走 x-acs 头。
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
            raise DingTalkApiRequestError(message, errcode=int(errcode))
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


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError
    return remaining
