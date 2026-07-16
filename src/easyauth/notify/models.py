from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, ClassVar, Final, override

from django.db import models
from django.db.models import Q

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AppNotificationChannel

if TYPE_CHECKING:
    from datetime import date, datetime

# ---- 消息模板 ----
NOTIFY_TEMPLATE_TEXT: Final = "text"
NOTIFY_TEMPLATE_MARKDOWN: Final = "markdown"
NOTIFY_TEMPLATE_ACTION_CARD: Final = "action_card"
NOTIFY_TEMPLATE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (NOTIFY_TEMPLATE_TEXT, "text"),
    (NOTIFY_TEMPLATE_MARKDOWN, "markdown"),
    (NOTIFY_TEMPLATE_ACTION_CARD, "action_card"),
)
NOTIFY_TEMPLATE_VALUES: Final[tuple[str, ...]] = (
    NOTIFY_TEMPLATE_TEXT,
    NOTIFY_TEMPLATE_MARKDOWN,
    NOTIFY_TEMPLATE_ACTION_CARD,
)

# ---- 消息聚合状态 ----
NOTIFY_MESSAGE_STATUS_PENDING: Final = "pending"
NOTIFY_MESSAGE_STATUS_SENDING: Final = "sending"
NOTIFY_MESSAGE_STATUS_COMPLETED: Final = "completed"
NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED: Final = "partially_failed"
NOTIFY_MESSAGE_STATUS_FAILED: Final = "failed"
NOTIFY_MESSAGE_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (NOTIFY_MESSAGE_STATUS_PENDING, "pending"),
    (NOTIFY_MESSAGE_STATUS_SENDING, "sending"),
    (NOTIFY_MESSAGE_STATUS_COMPLETED, "completed"),
    (NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED, "partially_failed"),
    (NOTIFY_MESSAGE_STATUS_FAILED, "failed"),
)
NOTIFY_MESSAGE_STATUS_VALUES: Final[tuple[str, ...]] = (
    NOTIFY_MESSAGE_STATUS_PENDING,
    NOTIFY_MESSAGE_STATUS_SENDING,
    NOTIFY_MESSAGE_STATUS_COMPLETED,
    NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED,
    NOTIFY_MESSAGE_STATUS_FAILED,
)

# ---- 收件人状态 ----
NOTIFY_RECIPIENT_STATUS_PENDING: Final = "pending"
NOTIFY_RECIPIENT_STATUS_SENT: Final = "sent"
NOTIFY_RECIPIENT_STATUS_DELIVERED: Final = "delivered"
NOTIFY_RECIPIENT_STATUS_FAILED: Final = "failed"
NOTIFY_RECIPIENT_STATUS_THROTTLED: Final = "throttled"
NOTIFY_RECIPIENT_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (NOTIFY_RECIPIENT_STATUS_PENDING, "pending"),
    (NOTIFY_RECIPIENT_STATUS_SENT, "sent"),
    (NOTIFY_RECIPIENT_STATUS_DELIVERED, "delivered"),
    (NOTIFY_RECIPIENT_STATUS_FAILED, "failed"),
    (NOTIFY_RECIPIENT_STATUS_THROTTLED, "throttled"),
)
NOTIFY_RECIPIENT_STATUS_VALUES: Final[tuple[str, ...]] = (
    NOTIFY_RECIPIENT_STATUS_PENDING,
    NOTIFY_RECIPIENT_STATUS_SENT,
    NOTIFY_RECIPIENT_STATUS_DELIVERED,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_THROTTLED,
)
# scoped user_ref v1 的三个目录字段各允许 128 个 Unicode 字符。按每字符最多
# 4 UTF-8 bytes、无 padding base64url 计算, 每段最多 683 字符, 加 dt:v1 与分隔符
# 共 2057 字符。4096 完整覆盖 v1, 并为后续引用版本保留约一倍的协议余量。
NOTIFY_SCOPED_REF_V1_MAX_CHARS: Final = 2057
NOTIFY_RAW_REF_MAX_CHARS: Final = 4096

# ---- error_code 枚举(契约 §N4) ----
NOTIFY_ERROR_USER_NOT_FOUND: Final = "USER_NOT_FOUND"
NOTIFY_ERROR_NO_DINGTALK_ID: Final = "NO_DINGTALK_ID"
NOTIFY_ERROR_USER_INACTIVE: Final = "USER_INACTIVE"
NOTIFY_ERROR_USER_AMBIGUOUS: Final = "USER_AMBIGUOUS"
NOTIFY_ERROR_USER_SCOPE_MISMATCH: Final = "USER_SCOPE_MISMATCH"
NOTIFY_ERROR_DINGTALK_REJECTED: Final = "DINGTALK_REJECTED"
NOTIFY_ERROR_DINGTALK_DUPLICATE: Final = "DINGTALK_DUPLICATE"
NOTIFY_ERROR_DINGTALK_DAILY_LIMIT: Final = "DINGTALK_DAILY_LIMIT"
NOTIFY_ERROR_EXHAUSTED: Final = "EXHAUSTED"

CREDENTIAL_TYPE_STATIC_TOKEN: Final = "static_token"  # noqa: S105 - 凭据类型枚举, 非密钥。
CREDENTIAL_TYPE_OAUTH_CLIENT: Final = "oauth_client"


class NotifyMessage(models.Model):
    # 一次 POST /notify/messages 调用 = 一行。公开 message_id 即 UUID 主键。
    if TYPE_CHECKING:
        app_id: ClassVar[int]

    id: models.UUIDField[uuid.UUID, uuid.UUID] = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="notify_messages",
    )
    channel: models.ForeignKey[AppNotificationChannel, AppNotificationChannel] = models.ForeignKey(
        AppNotificationChannel,
        on_delete=models.PROTECT,
        related_name="notify_messages",
    )
    template: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=NOTIFY_TEMPLATE_CHOICES,
    )
    title: models.CharField[str, str] = models.CharField(max_length=100, blank=True)
    content: models.TextField[str, str] = models.TextField()
    deeplink_url: models.CharField[str, str] = models.CharField(max_length=512, blank=True)
    # action_card 按钮文案; 空串表示投递时回落默认「查看详情」(契约 §N2)。
    deeplink_title: models.CharField[str, str] = models.CharField(
        max_length=20,
        blank=True,
        default="",
    )
    # APP 内幂等键: 同 (app, dedup_key) 只受理一次, 永久有效。
    dedup_key: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    # 规范化载荷 sha256; dedup_key 命中但 hash 不同 → 409 CONFLICT。
    payload_hash: models.CharField[str, str] = models.CharField(max_length=64)
    biz_tag: models.CharField[str, str] = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
    )
    status: models.CharField[str, str] = models.CharField(
        max_length=20,
        choices=NOTIFY_MESSAGE_STATUS_CHOICES,
        default=NOTIFY_MESSAGE_STATUS_PENDING,
    )

    # ---- 投递骨架(claim/lease/attempts) ----
    attempts: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    claim_token: models.CharField[str, str] = models.CharField(max_length=32, blank=True)
    lease_expires_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(null=True, blank=True)
    last_error: models.TextField[str, str] = models.TextField(blank=True)

    # ---- 去范式化计数 ----
    recipient_total: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(
        default=0,
    )
    recipient_sent: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(
        default=0,
    )
    recipient_failed: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(
        default=0,
    )

    # ---- 调用方溯源 ----
    requested_credential_type: models.CharField[str, str] = models.CharField(max_length=32)
    requested_credential_id: models.IntegerField[int, int] = models.IntegerField()

    completed_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(null=True, blank=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["app", "dedup_key"],
                condition=~Q(dedup_key=""),
                name="notify_message_dedup_unique",
            ),
            models.CheckConstraint(
                condition=Q(status__in=NOTIFY_MESSAGE_STATUS_VALUES),
                name="notify_message_status_supported",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["app", "status"], name="notify_msg_app_status_idx"),
            models.Index(fields=["app", "created_at"], name="notify_msg_app_created_idx"),
            models.Index(
                fields=["status", "lease_expires_at"],
                name="notify_msg_lease_idx",
            ),
        ]
        ordering: ClassVar[list[str]] = ["-created_at", "id"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.id}"


class NotifyRecipient(models.Model):
    # 一个收件人 = 一行; 投递状态机的最小粒度。
    if TYPE_CHECKING:
        message_id: ClassVar[uuid.UUID]
        user_id: ClassVar[int | None]
        id: ClassVar[int]

    message: models.ForeignKey[NotifyMessage, NotifyMessage] = models.ForeignKey(
        NotifyMessage,
        on_delete=models.CASCADE,
        related_name="recipients",
    )
    # 调用方 opaque 原始引用(原样回显): Authentik sub、legacy dt 或 canonical scoped dt ref。
    raw_ref: models.CharField[str, str] = models.CharField(max_length=NOTIFY_RAW_REF_MAX_CHARS)
    # 解析结果: 绑定的 UserMirror(可空: dt: 引用可能没有登录过的镜像行)
    user: models.ForeignKey[UserMirror | None, UserMirror | None] = models.ForeignKey(
        UserMirror,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="notify_recipients",
    )
    dingtalk_corp_id: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    dingtalk_source_slug: models.CharField[str, str] = models.CharField(
        max_length=128,
        blank=True,
        default="",
    )
    dingtalk_userid: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    status: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=NOTIFY_RECIPIENT_STATUS_CHOICES,
        default=NOTIFY_RECIPIENT_STATUS_PENDING,
    )
    error_code: models.CharField[str, str] = models.CharField(max_length=64, blank=True)
    error: models.TextField[str, str] = models.TextField(blank=True)
    # 钉钉 asyncsend_v2 返回的 task_id(int64 存字符串防精度问题)
    dingtalk_task_id: models.CharField[str, str] = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
    )
    sent_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(null=True, blank=True)
    delivered_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(null=True, blank=True)
    last_reconciled_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=[
                    "message",
                    "dingtalk_source_slug",
                    "dingtalk_corp_id",
                    "dingtalk_userid",
                ],
                condition=(
                    ~Q(dingtalk_userid="")
                    & ~Q(dingtalk_source_slug="")
                    & ~Q(dingtalk_corp_id="")
                ),
                name="notify_recipient_scoped_target_unique",
            ),
            models.UniqueConstraint(
                fields=["message", "dingtalk_userid"],
                condition=(
                    ~Q(dingtalk_userid="")
                    & (Q(dingtalk_source_slug="") | Q(dingtalk_corp_id=""))
                ),
                name="notify_recipient_legacy_target_unique",
            ),
            models.CheckConstraint(
                condition=Q(status__in=NOTIFY_RECIPIENT_STATUS_VALUES),
                name="notify_recipient_status_supported",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["message", "status"], name="notify_rcpt_msg_status_idx"),
        ]
        ordering: ClassVar[list[str]] = ["message_id", "id"]

    @override
    def __str__(self) -> str:
        return f"{self.message_id}:{self.raw_ref}:{self.status}"
