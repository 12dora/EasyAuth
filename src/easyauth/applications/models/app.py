"""定义应用主体, 平台能力与通知通道模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, override

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from easyauth.config.crypto import EncryptedCharField

from .constants import (
    CAPABILITY_CHOICES,
    HANDOVER_CAPABILITY_CHOICES,
    HANDOVER_CAPABILITY_NONE,
    HANDOVER_CAPABILITY_UNDECLARED,
    HANDOVER_CAPABILITY_VALUES,
    JsonValue,
)

if TYPE_CHECKING:
    from datetime import date, datetime


class App(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        app_id: ClassVar[int]

    app_key: models.CharField[str, str] = models.CharField(max_length=64, unique=True)
    name: models.CharField[str, str] = models.CharField(max_length=128)
    description: models.TextField[str, str] = models.TextField(blank=True)
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    catalog_version: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=1)
    handover_capability: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=HANDOVER_CAPABILITY_CHOICES,
        default=HANDOVER_CAPABILITY_UNDECLARED,
    )
    handover_asset_types: models.JSONField[list[JsonValue], list[JsonValue]] = models.JSONField(
        default=list,
        blank=True,
    )
    handover_capability_declared_by: models.CharField[str, str] = models.CharField(
        max_length=128,
        blank=True,
    )
    handover_capability_declared_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    handover_capability_synced_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    descriptor_base_url: models.CharField[str, str] = models.CharField(
        max_length=512,
        blank=True,
    )
    descriptor_token: EncryptedCharField = EncryptedCharField(
        max_length=1024,
        blank=True,
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["app_key"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(handover_capability__in=HANDOVER_CAPABILITY_VALUES),
                name="applications_app_handover_capability_supported",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        handover_capability=HANDOVER_CAPABILITY_NONE,
                        handover_capability_declared_by__gt="",
                        handover_capability_declared_at__isnull=False,
                    )
                    | ~Q(handover_capability=HANDOVER_CAPABILITY_NONE)
                ),
                name="applications_app_handover_none_requires_declaration",
            ),
        ]

    @override
    def __str__(self) -> str:
        return self.app_key


class AppCapability(models.Model):
    # App 维度的平台能力开关(目录/通知)。manifest 只能"申明"能力,
    # 开通必须由超管在 console 显式执行(申明 ≠ 授予)。
    if TYPE_CHECKING:
        id: ClassVar[int]
        app_id: ClassVar[int]

    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="platform_capabilities",
    )
    capability: models.CharField[str, str] = models.CharField(
        max_length=32,
        choices=CAPABILITY_CHOICES,
    )
    enabled: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    # 能力级配置。notify: {"daily_recipient_quota": 5000, "rate_per_minute": 60};
    # directory: 预留(如未来的字段分级)。空 dict 表示全部取默认值。
    config: models.JSONField[dict[str, JsonValue], dict[str, JsonValue]] = models.JSONField(
        default=dict,
        blank=True,
    )
    updated_by: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["app", "capability"],
                name="applications_app_capability_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["app__app_key", "capability"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.capability}"


class AppNotificationChannel(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        app_id: ClassVar[int]

    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="notification_channels",
    )
    name: models.CharField[str, str] = models.CharField(max_length=128)
    dingtalk_app_key: models.CharField[str, str] = models.CharField(max_length=128)
    dingtalk_app_secret: EncryptedCharField = EncryptedCharField(max_length=1024)
    agent_id: models.CharField[str, str] = models.CharField(max_length=64)
    directory_source_slug: models.CharField[str, str] = models.CharField(max_length=128)
    corp_id: models.CharField[str, str] = models.CharField(max_length=128)
    version: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    created_by: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["app", "version"],
                name="applications_notify_channel_app_version_unique",
            ),
            models.UniqueConstraint(
                fields=["app"],
                condition=Q(is_active=True),
                name="applications_notify_channel_one_active",
            ),
        ]
        ordering: ClassVar[list[str]] = ["app__app_key", "-version"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.version}"

    @override
    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        required_values = {
            "name": self.name,
            "dingtalk_app_key": self.dingtalk_app_key,
            "dingtalk_app_secret": self.dingtalk_app_secret,
            "agent_id": self.agent_id,
            "directory_source_slug": self.directory_source_slug,
            "corp_id": self.corp_id,
        }
        for field_name, value in required_values.items():
            if not value.strip():
                errors[field_name] = "通知通道字段不能为空。"
        if self.version < 1:
            errors["version"] = "通知通道版本必须大于零。"
        if errors:
            raise ValidationError(errors)
