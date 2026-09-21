from __future__ import annotations

from typing import Final

DINGTALK_NOT_CONFIGURED_MESSAGE: Final = "钉钉集成凭证未配置。"

type DingTalkJson = dict[str, object]


class DingTalkApiError(RuntimeError):
    pass


class DingTalkNotConfiguredError(DingTalkApiError):
    def __init__(self) -> None:
        super().__init__(DINGTALK_NOT_CONFIGURED_MESSAGE)


class DingTalkApiUnavailableError(DingTalkApiError):
    pass


class DingTalkCallBudgetExceededError(DingTalkApiUnavailableError):
    """用量策略拒绝本次钉钉调用; HTTP 请求未发出。"""


class DingTalkApiRequestError(DingTalkApiError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        errcode: int | None = None,
    ) -> None:
        super().__init__(message)
        # HTTP 层状态码(urlopen HTTPError); 与 oapi 业务 errcode 分离。
        self.status_code: int | None = status_code
        # 旧版 oapi 响应体 errcode(如 90018/143103); HTTP 失败时为 None。
        self.errcode: int | None = errcode
