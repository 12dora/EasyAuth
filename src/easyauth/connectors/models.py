from __future__ import annotations

import json
from typing import TYPE_CHECKING, ClassVar, Final, cast, override

from django.db import models
from django.db.models import Q

from easyauth.applications.models import App, AuthorizationGroup
from easyauth.config.crypto import EncryptedTextField

if TYPE_CHECKING:
    from datetime import date, datetime

    from easyauth.applications.ops_models import JsonValue

SYNC_TRIGGER_PERIODIC: Final = "periodic"
SYNC_TRIGGER_EVENT: Final = "event"
SYNC_TRIGGER_MANUAL: Final = "manual"
SYNC_TRIGGER_OFFBOARD: Final = "offboard"
SYNC_TRIGGER_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (SYNC_TRIGGER_PERIODIC, "periodic"),
    (SYNC_TRIGGER_EVENT, "event"),
    (SYNC_TRIGGER_MANUAL, "manual"),
    (SYNC_TRIGGER_OFFBOARD, "offboard"),
)
SYNC_TRIGGER_VALUES: Final[tuple[str, ...]] = (
    SYNC_TRIGGER_PERIODIC,
    SYNC_TRIGGER_EVENT,
    SYNC_TRIGGER_MANUAL,
    SYNC_TRIGGER_OFFBOARD,
)

SYNC_RUN_STATUS_SUCCESS: Final = "success"
SYNC_RUN_STATUS_PARTIAL: Final = "partial"
SYNC_RUN_STATUS_FAILED: Final = "failed"
SYNC_RUN_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (SYNC_RUN_STATUS_SUCCESS, "success"),
    (SYNC_RUN_STATUS_PARTIAL, "partial"),
    (SYNC_RUN_STATUS_FAILED, "failed"),
)
SYNC_RUN_STATUS_VALUES: Final[tuple[str, ...]] = (
    SYNC_RUN_STATUS_SUCCESS,
    SYNC_RUN_STATUS_PARTIAL,
    SYNC_RUN_STATUS_FAILED,
)

DEFAULT_RECONCILE_INTERVAL_SECONDS: Final = 300


class ConnectorInstance(models.Model):
    # 一个 App 的一种出站供给连接器配置(方案 §3.3): 凭据整体随 JSON 载荷静态加密,
    # 健康字段由对账编排回写、供控制台状态卡与依赖健康面板消费。
    if TYPE_CHECKING:
        id: ClassVar[int]
        app_id: ClassVar[int]

    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="connector_instances",
    )
    connector_key: models.CharField[str, str] = models.CharField(max_length=64)
    enabled: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    # 完整配置 JSON(含 x-secret 字段)静态加密落库; 读接口不回显敏感字段。
    config_encrypted: EncryptedTextField = EncryptedTextField(blank=True, default="")
    reconcile_interval_seconds: models.PositiveIntegerField[int, int] = (
        models.PositiveIntegerField(default=DEFAULT_RECONCILE_INTERVAL_SECONDS)
    )
    last_reconcile_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    last_status: models.CharField[str, str] = models.CharField(max_length=16, blank=True)
    last_error: models.TextField[str, str] = models.TextField(blank=True)
    consecutive_failures: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(
        default=0,
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
                fields=["app", "connector_key"],
                name="connectors_instance_app_connector_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["app__app_key", "connector_key"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.connector_key}"

    @property
    def config(self) -> dict[str, JsonValue]:
        if not self.config_encrypted:
            return {}
        parsed = cast("object", json.loads(self.config_encrypted))
        if not isinstance(parsed, dict):
            return {}
        return cast("dict[str, JsonValue]", parsed)

    def set_config(self, config: dict[str, JsonValue]) -> None:
        self.config_encrypted = json.dumps(config, ensure_ascii=False, sort_keys=True)


class ConnectorMapping(models.Model):
    # 授权组 ↔ 外部组(方案 §3.3): external_ref 的语义由连接器定义(NetBird 取组名);
    # 对账只增删映射表管理的外部组, 外部系统手工维护的其他组不受影响。
    if TYPE_CHECKING:
        id: ClassVar[int]
        instance_id: ClassVar[int]
        authorization_group_id: ClassVar[int]

    instance: models.ForeignKey[ConnectorInstance, ConnectorInstance] = models.ForeignKey(
        ConnectorInstance,
        on_delete=models.CASCADE,
        related_name="mappings",
    )
    authorization_group: models.ForeignKey[AuthorizationGroup, AuthorizationGroup] = (
        models.ForeignKey(
            AuthorizationGroup,
            on_delete=models.CASCADE,
            related_name="connector_mappings",
        )
    )
    external_ref: models.CharField[str, str] = models.CharField(max_length=255)
    auto_create: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["instance", "authorization_group"],
                name="connectors_mapping_instance_group_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["instance_id", "authorization_group__key"]

    @override
    def __str__(self) -> str:
        return f"{self.instance}:{self.authorization_group.key}->{self.external_ref}"


class ConnectorSyncRun(models.Model):
    # 对账运行审计(方案 §3.3): 控制台运行历史直接消费; 只保留最近 N 条(清理任务)。
    if TYPE_CHECKING:
        id: ClassVar[int]
        instance_id: ClassVar[int]

    instance: models.ForeignKey[ConnectorInstance, ConnectorInstance] = models.ForeignKey(
        ConnectorInstance,
        on_delete=models.CASCADE,
        related_name="sync_runs",
    )
    trigger: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=SYNC_TRIGGER_CHOICES,
    )
    started_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField()
    finished_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField()
    status: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=SYNC_RUN_STATUS_CHOICES,
    )
    stats: models.JSONField[dict[str, JsonValue], dict[str, JsonValue]] = models.JSONField(
        default=dict,
    )
    error: models.TextField[str, str] = models.TextField(blank=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(trigger__in=SYNC_TRIGGER_VALUES),
                name="connectors_sync_run_trigger_supported",
            ),
            models.CheckConstraint(
                condition=Q(status__in=SYNC_RUN_STATUS_VALUES),
                name="connectors_sync_run_status_supported",
            ),
        ]
        ordering: ClassVar[list[str]] = ["-started_at", "-id"]

    @override
    def __str__(self) -> str:
        return f"{self.instance}:{self.trigger}:{self.status}"
