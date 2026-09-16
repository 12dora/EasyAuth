from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, override
from zoneinfo import ZoneInfo

from easyauth.notify.models import (
    NOTIFY_ERROR_DINGTALK_DAILY_LIMIT,
    NOTIFY_ERROR_DINGTALK_DUPLICATE,
    NOTIFY_ERROR_DINGTALK_REJECTED,
    NOTIFY_ERROR_EXHAUSTED,
    NOTIFY_ERROR_NO_DINGTALK_ID,
    NOTIFY_ERROR_ROBOT_REJECTED,
    NOTIFY_ERROR_USER_AMBIGUOUS,
    NOTIFY_ERROR_USER_INACTIVE,
    NOTIFY_ERROR_USER_NOT_FOUND,
    NOTIFY_ERROR_USER_SCOPE_MISMATCH,
    NOTIFY_MESSAGE_STATUS_COMPLETED,
    NOTIFY_MESSAGE_STATUS_FAILED,
    NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED,
    NOTIFY_MESSAGE_STATUS_PENDING,
    NOTIFY_MESSAGE_STATUS_SENDING,
    NOTIFY_RAW_REF_MAX_CHARS,
    NOTIFY_RECIPIENT_STATUS_DELIVERED,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_PENDING,
    NOTIFY_RECIPIENT_STATUS_SENT,
    NOTIFY_RECIPIENT_STATUS_THROTTLED,
    NOTIFY_TEMPLATE_OA,
    NotifyMessage,
)

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror


__all__ = [
    "ACCEPT_TIME_ERROR_CODES",
    "APP_DISPLAY_NAME_TOO_LONG_MESSAGE",
    "AUTHOR_TOO_LONG_MESSAGE",
    "BIZ_TAG_TOO_LONG_MESSAGE",
    "CONTENT_REQUIRED_MESSAGE",
    "DAILY_QUOTA_EXCEEDED_MESSAGE",
    "DEDUP_KEY_TOO_LONG_MESSAGE",
    "DEEPLINK_URL_INVALID_MESSAGE",
    "DEFAULT_DAILY_RECIPIENT_QUOTA",
    "DEFAULT_RETENTION_DAYS",
    "DINGTALK_AGENT_MISSING_MESSAGE",
    "DINGTALK_LINK_PREFIX",
    "DINGTALK_PROGRESS_DONE",
    "DINGTALK_THROTTLE_ERRCODES",
    "DINGTALK_USER_STATUS_ACTIVE",
    "FIELDS_INVALID_MESSAGE",
    "FIELDS_TIME_KEY_RESERVED_MESSAGE",
    "FIELDS_TOO_MANY_MESSAGE",
    "HTTPS_PREFIX",
    "IDEMPOTENCY_PAYLOAD_CONFLICT_MESSAGE",
    "MAX_DELIVERY_ATTEMPTS",
    "MSG_TOO_LARGE_MESSAGE",
    "NOTIFY_APP_DISPLAY_NAME_MAX_CHARS",
    "NOTIFY_AUTHOR_MAX_CHARS",
    "NOTIFY_BATCH_SIZE",
    "NOTIFY_BIZ_TAG_MAX_CHARS",
    "NOTIFY_CHANNEL_MISSING_MESSAGE",
    "NOTIFY_DEDUP_KEY_MAX_CHARS",
    "NOTIFY_DEEPLINK_URL_MAX_CHARS",
    "NOTIFY_DELIVERY_TASK_NAME",
    "NOTIFY_ERROR_DINGTALK_DAILY_LIMIT",
    "NOTIFY_ERROR_DINGTALK_DUPLICATE",
    "NOTIFY_ERROR_DINGTALK_REJECTED",
    "NOTIFY_ERROR_EXHAUSTED",
    "NOTIFY_ERROR_MAX_CHARS",
    "NOTIFY_ERROR_NO_DINGTALK_ID",
    "NOTIFY_ERROR_ROBOT_REJECTED",
    "NOTIFY_ERROR_USER_AMBIGUOUS",
    "NOTIFY_ERROR_USER_INACTIVE",
    "NOTIFY_ERROR_USER_NOT_FOUND",
    "NOTIFY_ERROR_USER_SCOPE_MISMATCH",
    "NOTIFY_FORM_DISPLAY_MAX_ITEMS",
    "NOTIFY_FORM_FIELD_MAX_ITEMS",
    "NOTIFY_FORM_KEY_MAX_CHARS",
    "NOTIFY_FORM_VALUE_MAX_CHARS",
    "NOTIFY_LEASE_SECONDS",
    "NOTIFY_MAX_CHUNKS_PER_RUN",
    "NOTIFY_MAX_RECIPIENTS",
    "NOTIFY_MESSAGE_STATUS_COMPLETED",
    "NOTIFY_MESSAGE_STATUS_FAILED",
    "NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED",
    "NOTIFY_MESSAGE_STATUS_PENDING",
    "NOTIFY_MESSAGE_STATUS_SENDING",
    "NOTIFY_MIN_RECIPIENTS",
    "NOTIFY_MSG_MAX_BYTES",
    "NOTIFY_PRUNE_BATCH_SIZE",
    "NOTIFY_PRUNE_TASK_NAME",
    "NOTIFY_RECIPIENT_STATUS_DELIVERED",
    "NOTIFY_RECIPIENT_STATUS_FAILED",
    "NOTIFY_RECIPIENT_STATUS_PENDING",
    "NOTIFY_RECIPIENT_STATUS_SENT",
    "NOTIFY_RECIPIENT_STATUS_THROTTLED",
    "NOTIFY_RECONCILE_TASK_LIMIT",
    "NOTIFY_RECONCILE_TASK_NAME",
    "NOTIFY_RECONCILE_WINDOW_HOURS",
    "NOTIFY_RETRY_DELAYS_SECONDS",
    "NOTIFY_TEMPLATE_OA",
    "NOTIFY_THROTTLE_RETRY_SECONDS",
    "NOTIFY_TITLE_MAX_CHARS",
    "OA_BODY_TITLE_MAX_CHARS",
    "OA_BODY_TITLE_SEPARATOR",
    "RAW_REF_TOO_LONG_MESSAGE",
    "RECIPIENTS_REQUIRED_MESSAGE",
    "SHANGHAI_TZ",
    "TITLE_REQUIRED_MESSAGE",
    "TITLE_TOO_LONG_MESSAGE",
    "AcceptNotifyResult",
    "NotifyAcceptError",
    "ResolvedRecipient",
]

type NotifyAcceptErrorKind = Literal[
    "conflict",
    "dependency_unavailable",
    "throttled",
    "validation_error",
]

logger = logging.getLogger(__name__)

NOTIFY_DELIVERY_TASK_NAME: Final = "easyauth.notify.deliver_message"
NOTIFY_RECONCILE_TASK_NAME: Final = "easyauth.notify.reconcile_send_results"
NOTIFY_PRUNE_TASK_NAME: Final = "easyauth.notify.prune_messages"
NOTIFY_MSG_MAX_BYTES: Final = 2048
NOTIFY_MAX_RECIPIENTS: Final = 500
NOTIFY_MIN_RECIPIENTS: Final = 1
NOTIFY_TITLE_MAX_CHARS: Final = 100
NOTIFY_DEEPLINK_URL_MAX_CHARS: Final = 500
NOTIFY_APP_DISPLAY_NAME_MAX_CHARS: Final = 128
NOTIFY_AUTHOR_MAX_CHARS: Final = 64
# 钉钉 body.form 最多显示 6 条, 第 0 条由平台写入「时间」, 调用方至多 5 项。
NOTIFY_FORM_DISPLAY_MAX_ITEMS: Final = 6
NOTIFY_FORM_FIELD_MAX_ITEMS: Final = NOTIFY_FORM_DISPLAY_MAX_ITEMS - 1
# 下列为卡片展示约束, 不是钉钉文档里的硬上限; 超长 value 会在客户端被截断。
NOTIFY_FORM_KEY_MAX_CHARS: Final = 20
NOTIFY_FORM_VALUE_MAX_CHARS: Final = 100
# 钉钉建议 body.title 50 字以内; 合成「应用名 · 标题」压到 40, 只截标题部分。
OA_BODY_TITLE_MAX_CHARS: Final = 40
OA_BODY_TITLE_SEPARATOR: Final = " · "
NOTIFY_DEDUP_KEY_MAX_CHARS: Final = 128
NOTIFY_BIZ_TAG_MAX_CHARS: Final = 64
DEFAULT_DAILY_RECIPIENT_QUOTA: Final = 5000
SHANGHAI_TZ: Final = ZoneInfo("Asia/Shanghai")
HTTPS_PREFIX: Final = "https://"
DINGTALK_LINK_PREFIX: Final = "dingtalk://dingtalkclient/page/link?"
DINGTALK_USER_STATUS_ACTIVE: Final = "active"

# 投递管道常量
NOTIFY_RETRY_DELAYS_SECONDS: Final[tuple[int, ...]] = (60, 300, 1800, 7200)
NOTIFY_THROTTLE_RETRY_SECONDS: Final = 120
NOTIFY_MAX_CHUNKS_PER_RUN: Final = 5
NOTIFY_BATCH_SIZE: Final = 100
NOTIFY_LEASE_SECONDS: Final = 45
NOTIFY_ERROR_MAX_CHARS: Final = 500
NOTIFY_RECONCILE_WINDOW_HOURS: Final = 24
NOTIFY_RECONCILE_TASK_LIMIT: Final = 50
NOTIFY_PRUNE_BATCH_SIZE: Final = 500
DEFAULT_RETENTION_DAYS: Final = 180
DINGTALK_PROGRESS_DONE: Final = 2
# 调用级频控 errcode: QPS 90018, QPM 人次 143103/143104。
DINGTALK_THROTTLE_ERRCODES: Final[frozenset[int]] = frozenset({90018, 143103, 143104})
# 受理期解析失败集合: 幂等重放时 recipient_rejected 只计这些(契约 §N2)。
ACCEPT_TIME_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        NOTIFY_ERROR_USER_NOT_FOUND,
        NOTIFY_ERROR_NO_DINGTALK_ID,
        NOTIFY_ERROR_USER_INACTIVE,
        NOTIFY_ERROR_USER_AMBIGUOUS,
        NOTIFY_ERROR_USER_SCOPE_MISMATCH,
    },
)
MAX_DELIVERY_ATTEMPTS: Final = len(NOTIFY_RETRY_DELAYS_SECONDS) + 1

IDEMPOTENCY_PAYLOAD_CONFLICT_MESSAGE: Final = "同一 dedup_key 已使用不同的通知载荷。"
DAILY_QUOTA_EXCEEDED_MESSAGE: Final = "通知每日收件人配额已用尽。"
RECIPIENTS_REQUIRED_MESSAGE: Final = "recipients 必须为 1~500 个用户引用。"
TITLE_REQUIRED_MESSAGE: Final = "必须提供 title。"
TITLE_TOO_LONG_MESSAGE: Final = "title 不得超过 100 字符。"
CONTENT_REQUIRED_MESSAGE: Final = "content 不能为空。"
DEEPLINK_URL_INVALID_MESSAGE: Final = (
    "deeplink_url 须为含主机名的 https URL, 或以 "
    "dingtalk://dingtalkclient/page/link? 开头且内嵌含主机名的 https URL, 且长度 ≤500。"
)
FIELDS_INVALID_MESSAGE: Final = "fields 必须为 {key, value} 字符串对象列表。"
FIELDS_TOO_MANY_MESSAGE: Final = "fields 至多 5 项(加上系统「时间」后钉钉最多显示 6 条)。"
FIELDS_TIME_KEY_RESERVED_MESSAGE: Final = "fields 不得使用保留键「时间」。"
APP_DISPLAY_NAME_TOO_LONG_MESSAGE: Final = "app_display_name 不得超过 128 字符。"
AUTHOR_TOO_LONG_MESSAGE: Final = "author 不得超过 64 字符。"
DEDUP_KEY_TOO_LONG_MESSAGE: Final = "dedup_key 不得超过 128 字符。"
BIZ_TAG_TOO_LONG_MESSAGE: Final = "biz_tag 不得超过 64 字符。"
MSG_TOO_LARGE_MESSAGE: Final = "组装后的钉钉 msg JSON 超过 2048 字节上限。"
RAW_REF_TOO_LONG_MESSAGE: Final = f"收件人引用不得超过 {NOTIFY_RAW_REF_MAX_CHARS} 字符。"
DINGTALK_AGENT_MISSING_MESSAGE: Final = "钉钉工作通知 agent_id 未配置。"
NOTIFY_CHANNEL_MISSING_MESSAGE: Final = "应用未配置可用的钉钉通知通道。"


@dataclass(frozen=True, slots=True)
class NotifyAcceptError(Exception):
    kind: NotifyAcceptErrorKind
    message: str
    field: str = ""
    retry_after_seconds: int | None = None

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class AcceptNotifyResult:
    message: NotifyMessage
    accepted: bool
    recipient_total: int
    recipient_rejected: int


@dataclass(frozen=True, slots=True)
class ResolvedRecipient:
    raw_ref: str
    user: UserMirror | None
    dingtalk_corp_id: str
    dingtalk_source_slug: str
    dingtalk_userid: str
    status: str
    error_code: str
    error: str
