from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, override

from django.db import models
from django.db.models import Q

from easyauth.applications.models import App
from easyauth.config.crypto import EncryptedCharField
from easyauth.config.net import parse_https_url

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date, datetime

    from django.db.models.base import ModelBase

    from easyauth.applications.ops_models import JsonValue

WEBHOOK_EVENT_APPROVAL_COMPLETED: Final = "approval.completed"
WEBHOOK_EVENT_HANDOVER_PREVIEW: Final = "lifecycle.handover.preview"
WEBHOOK_EVENT_HANDOVER_EXECUTE: Final = "lifecycle.handover.execute"
WEBHOOK_EVENT_TEST: Final = "webhook.test"

DELIVERY_STATUS_PENDING: Final = "pending"
DELIVERY_STATUS_DELIVERED: Final = "delivered"
DELIVERY_STATUS_FAILED: Final = "failed"
DELIVERY_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (DELIVERY_STATUS_PENDING, "pending"),
    (DELIVERY_STATUS_DELIVERED, "delivered"),
    (DELIVERY_STATUS_FAILED, "failed"),
)
DELIVERY_STATUS_VALUES: Final[tuple[str, ...]] = (
    DELIVERY_STATUS_PENDING,
    DELIVERY_STATUS_DELIVERED,
    DELIVERY_STATUS_FAILED,
)


class AppWebhookConfig(models.Model):
    # EasyAuth → APP 反向通道配置(§5.1): 每 APP 一份密钥, 事件 URL 接入时从
    # manifest 读入、控制台可覆盖。
    if TYPE_CHECKING:
        id: ClassVar[int]

    app: models.OneToOneField[App, App] = models.OneToOneField(
        App,
        on_delete=models.CASCADE,
        related_name="webhook_config",
    )
    secret: EncryptedCharField = EncryptedCharField(max_length=1024, blank=True)
    enabled: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    approval_callback_url: models.CharField[str, str] = models.CharField(
        max_length=512,
        blank=True,
    )
    handover_url: models.CharField[str, str] = models.CharField(max_length=512, blank=True)
    onboard_url: models.CharField[str, str] = models.CharField(max_length=512, blank=True)
    # 精确域名 allowlist 由三类 URL 自动生成, 调用方不能另行扩大范围。
    allowed_hosts: models.JSONField[list[str], list[str]] = models.JSONField(default=list)
    updated_by: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["app__app_key"]

    @override
    def __str__(self) -> str:
        return f"webhook-config:{self.app.app_key}"

    @override
    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        hosts: set[str] = set()
        for url in (
            self.approval_callback_url,
            self.handover_url,
            self.onboard_url,
        ):
            if url:
                hosts.add(parse_https_url(url).hostname)
        self.allowed_hosts = sorted(hosts)
        effective_update_fields = (
            None if update_fields is None else {*update_fields, "allowed_hosts"}
        )
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=effective_update_fields,
        )


class WebhookDelivery(models.Model):
    # 每次事件投递一行: 幂等键 delivery_id 即 X-EasyAuth-Delivery 头,
    # 失败重试与手动重投都在此行上推进。
    if TYPE_CHECKING:
        id: ClassVar[int]

    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="webhook_deliveries",
    )
    delivery_id: models.CharField[str, str] = models.CharField(max_length=64, unique=True)
    event_type: models.CharField[str, str] = models.CharField(max_length=64)
    target_url: models.CharField[str, str] = models.CharField(max_length=512)
    payload: models.JSONField[dict[str, JsonValue], dict[str, JsonValue]] = models.JSONField(
        default=dict,
    )
    status: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=DELIVERY_STATUS_CHOICES,
        default=DELIVERY_STATUS_PENDING,
    )
    attempts: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    generation: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=1)
    claim_token: models.CharField[str, str] = models.CharField(max_length=32, blank=True)
    lease_expires_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(null=True, blank=True)
    last_error: models.TextField[str, str] = models.TextField(blank=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(status__in=DELIVERY_STATUS_VALUES),
                name="webhooks_delivery_status_supported",
            ),
            models.CheckConstraint(
                condition=Q(generation__gte=1),
                name="webhooks_delivery_generation_positive",
            ),
        ]
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.event_type}:{self.delivery_id}"
