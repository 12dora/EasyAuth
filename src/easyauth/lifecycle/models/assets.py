"""定义交接资产分配, 批次计划, 执行批次与投递审计模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, override

from django.db import models
from django.db.models import Q

from easyauth.accounts.models import UserMirror

from .constants import (
    ASSET_ACTION_CHOICES,
    ASSET_ACTION_RELEASE,
    ASSET_ACTION_SKIP,
    ASSET_ACTION_TRANSFER,
    ASSET_ACTION_VALUES,
    BATCH_PLAN_STATUS_ACTIVE,
    BATCH_PLAN_STATUS_VALUES,
    BATCH_STATUS_VALUES,
    DELIVERY_OUTCOME_SENT,
    DELIVERY_OUTCOME_SUPERSEDED,
    DELIVERY_OUTCOME_VALUES,
)
from .task import HandoverAppAction

if TYPE_CHECKING:
    from datetime import date, datetime

    from easyauth.applications.ops_models import JsonValue


class HandoverAssetType(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        action_id: ClassVar[int]
        default_to_user_id: ClassVar[int | None]
        overrides: ClassVar[models.Manager[HandoverAssetOverride]]

    action: models.ForeignKey[HandoverAppAction, HandoverAppAction] = models.ForeignKey(
        HandoverAppAction,
        on_delete=models.CASCADE,
        related_name="asset_types",
    )
    generation: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    type_key: models.CharField[str, str] = models.CharField(max_length=64)
    label_snapshot: models.CharField[str, str] = models.CharField(max_length=120)
    count: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    detail_supported: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    releasable: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    default_action: models.CharField[str, str] = models.CharField(
        max_length=8,
        choices=ASSET_ACTION_CHOICES,
        default=ASSET_ACTION_SKIP,
    )
    default_to_user: models.ForeignKey[UserMirror | None, UserMirror | None] = models.ForeignKey(
        UserMirror,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="handover_default_receiving_types",
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["action", "generation", "type_key"],
                name="lifecycle_asset_type_unique_per_generation",
            ),
            models.CheckConstraint(
                condition=Q(default_action__in=ASSET_ACTION_VALUES),
                name="lifecycle_asset_type_action_supported",
            ),
            models.CheckConstraint(
                condition=(
                    Q(default_action=ASSET_ACTION_TRANSFER, default_to_user__isnull=False)
                    | (~Q(default_action=ASSET_ACTION_TRANSFER) & Q(default_to_user__isnull=True))
                ),
                name="lifecycle_asset_type_action_shape",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(default_action=ASSET_ACTION_RELEASE)
                    | Q(default_action=ASSET_ACTION_RELEASE, releasable=True)
                ),
                name="lifecycle_asset_type_release_requires_releasable",
            ),
        ]
        ordering: ClassVar[list[str]] = ["action_id", "generation", "type_key"]

    @override
    def __str__(self) -> str:
        return f"{self.action_id}:{self.type_key}:{self.default_action}"


class HandoverAssetOverride(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        asset_type_id: ClassVar[int]
        to_user_id: ClassVar[int | None]

    asset_type: models.ForeignKey[HandoverAssetType, HandoverAssetType] = models.ForeignKey(
        HandoverAssetType,
        on_delete=models.CASCADE,
        related_name="overrides",
    )
    asset_id: models.CharField[str, str] = models.CharField(max_length=128)
    label_snapshot: models.CharField[str, str] = models.CharField(max_length=120, blank=True)
    action: models.CharField[str, str] = models.CharField(
        max_length=8,
        choices=ASSET_ACTION_CHOICES,
    )
    to_user: models.ForeignKey[UserMirror | None, UserMirror | None] = models.ForeignKey(
        UserMirror,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="handover_override_receiving",
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["asset_type", "asset_id"],
                name="lifecycle_asset_override_unique",
            ),
            models.CheckConstraint(
                condition=Q(action__in=ASSET_ACTION_VALUES),
                name="lifecycle_asset_override_action_supported",
            ),
            models.CheckConstraint(
                condition=(
                    Q(action=ASSET_ACTION_TRANSFER, to_user__isnull=False)
                    | (~Q(action=ASSET_ACTION_TRANSFER) & Q(to_user__isnull=True))
                ),
                name="lifecycle_asset_override_action_shape",
            ),
        ]
        ordering: ClassVar[list[str]] = ["asset_type_id", "asset_id"]

    @override
    def __str__(self) -> str:
        return f"{self.asset_type_id}:{self.asset_id}:{self.action}"


class HandoverBatchPlan(models.Model):
    # 413 分片计划: 一次算好 M 批; batch 行在每批执行前才创建。
    if TYPE_CHECKING:
        id: ClassVar[int]
        action_id: ClassVar[int | None]

    action: models.ForeignKey[HandoverAppAction | None, HandoverAppAction | None] = (
        models.ForeignKey(
            HandoverAppAction,
            on_delete=models.SET_NULL,
            null=True,
            related_name="batch_plans",
        )
    )
    action_snapshot_id: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    generation: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    total: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    chunks: models.JSONField[list[JsonValue], list[JsonValue]] = models.JSONField()
    assignment_hash: models.CharField[str, str] = models.CharField(max_length=64)
    status: models.CharField[str, str] = models.CharField(max_length=16)
    completed_batches: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(
        default=0,
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["action_snapshot_id", "generation"],
                condition=Q(status=BATCH_PLAN_STATUS_ACTIVE),
                name="lifecycle_batch_plan_one_active",
            ),
            models.CheckConstraint(
                condition=Q(status__in=BATCH_PLAN_STATUS_VALUES),
                name="lifecycle_batch_plan_status_supported",
            ),
        ]

    @override
    def __str__(self) -> str:
        return f"plan:{self.action_snapshot_id}:g{self.generation}:{self.status}"


class HandoverExecutionBatch(models.Model):
    # 请求侧不可变(request_payload/request_hash/snapshot_token); status 可写。
    if TYPE_CHECKING:
        id: ClassVar[int]
        action_id: ClassVar[int | None]
        plan_id: ClassVar[int | None]

    action: models.ForeignKey[HandoverAppAction | None, HandoverAppAction | None] = (
        models.ForeignKey(
            HandoverAppAction,
            on_delete=models.SET_NULL,
            null=True,
            related_name="execution_batches",
        )
    )
    action_snapshot_id: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    generation: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    batch_seq: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    is_final: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    snapshot_token: models.CharField[str, str] = models.CharField(max_length=128)
    # 发出前固化, 之后只读(审计凭据); 不要用 save() 拦截整行, status 仍需写。
    request_payload: models.JSONField[dict[str, JsonValue], dict[str, JsonValue]] = (
        models.JSONField()
    )
    request_hash: models.CharField[str, str] = models.CharField(max_length=64)
    status: models.CharField[str, str] = models.CharField(max_length=16)
    data_completed_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    task_snapshot: models.JSONField[dict[str, JsonValue], dict[str, JsonValue]] = models.JSONField(
        default=dict,
    )
    plan: models.ForeignKey[HandoverBatchPlan | None, HandoverBatchPlan | None] = models.ForeignKey(
        HandoverBatchPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="batches",
    )
    plan_batch_no: models.PositiveIntegerField[int | None, int | None] = (
        models.PositiveIntegerField(blank=True, null=True)
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["action_snapshot_id", "generation", "batch_seq"],
                name="lifecycle_execution_batch_unique",
            ),
            models.CheckConstraint(
                condition=Q(status__in=BATCH_STATUS_VALUES),
                name="lifecycle_execution_batch_status_supported",
            ),
        ]

    @override
    def __str__(self) -> str:
        return f"batch:{self.action_snapshot_id}:g{self.generation}:b{self.batch_seq}"


class HandoverDeliveryAttempt(models.Model):
    # 受控单次状态转换: sent → succeeded|failed|async_accepted|superseded。
    if TYPE_CHECKING:
        id: ClassVar[int]
        batch_id: ClassVar[int]

    batch: models.ForeignKey[HandoverExecutionBatch, HandoverExecutionBatch] = models.ForeignKey(
        HandoverExecutionBatch,
        on_delete=models.PROTECT,
        related_name="deliveries",
    )
    delivery_seq: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    lease_fence: models.PositiveBigIntegerField[int, int] = models.PositiveBigIntegerField()
    outcome: models.CharField[str, str] = models.CharField(max_length=16)
    http_status: models.PositiveSmallIntegerField[int | None, int | None] = (
        models.PositiveSmallIntegerField(blank=True, null=True)
    )
    response_payload: models.JSONField[dict[str, JsonValue], dict[str, JsonValue]] = (
        models.JSONField(default=dict, blank=True)
    )
    error_text: models.TextField[str, str] = models.TextField(blank=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["batch", "delivery_seq"],
                name="lifecycle_delivery_attempt_unique",
            ),
            models.CheckConstraint(
                condition=Q(outcome__in=DELIVERY_OUTCOME_VALUES),
                name="lifecycle_delivery_outcome_supported",
            ),
            # sent/superseded 可无 HTTP 状态; 其它终态必须有 status 或 error_text。
            models.CheckConstraint(
                condition=(
                    Q(outcome__in=(DELIVERY_OUTCOME_SENT, DELIVERY_OUTCOME_SUPERSEDED))
                    | Q(http_status__isnull=False)
                    | ~Q(error_text="")
                ),
                name="lifecycle_delivery_terminal_evidence",
            ),
        ]

    @override
    def __str__(self) -> str:
        return f"delivery:{self.batch_id}:{self.delivery_seq}:{self.outcome}"
