"""定义交接任务, 应用动作及其审批与跳过审计模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, override

from django.db import models
from django.db.models import Q

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App

from .constants import (
    ACTION_STATUS_CHOICES,
    ACTION_STATUS_PENDING,
    ACTION_STATUS_VALUES,
    ASSIGNEE_STATE_CHOICES,
    ASSIGNEE_STATE_SUPERUSER_POOL,
    ASSIGNEE_STATE_VALUES,
    AUTHORITY_SOURCE_MANAGER_CHAIN,
    HANDOVER_KIND_CHOICES,
    HANDOVER_KIND_OFFBOARD,
    HANDOVER_KIND_PRE_OFFBOARD,
    HANDOVER_KIND_TRANSFER,
    HANDOVER_KIND_VALUES,
    TASK_OPEN_STATUSES,
    TASK_STATUS_CHOICES,
    TASK_STATUS_PENDING,
    TASK_STATUS_VALUES,
)

if TYPE_CHECKING:
    from datetime import date, datetime

    from easyauth.applications.models import ApprovalRule
    from easyauth.applications.ops_models import JsonValue


class HandoverTask(models.Model):
    # 交接单: 离职单由目录同步自动创建, 管理员可手动建单(含在职员工提前交接与转岗)。
    # 缓冲是常态: 无接收人时停在 pending/in_progress, 无期限, 数据原地保留。
    if TYPE_CHECKING:
        id: ClassVar[int]
        subject_user_id: ClassVar[int]
        assignee_id: ClassVar[int | None]

    kind: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=HANDOVER_KIND_CHOICES,
    )
    subject_user: models.ForeignKey[UserMirror, UserMirror] = models.ForeignKey(
        UserMirror,
        on_delete=models.PROTECT,
        related_name="handover_tasks",
    )
    status: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=TASK_STATUS_CHOICES,
        default=TASK_STATUS_PENDING,
    )
    assignee: models.ForeignKey[UserMirror | None, UserMirror | None] = models.ForeignKey(
        UserMirror,
        on_delete=models.PROTECT,
        related_name="handover_assignments",
        blank=True,
        null=True,
    )
    assignee_state: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=ASSIGNEE_STATE_CHOICES,
        default=ASSIGNEE_STATE_SUPERUSER_POOL,
    )
    escalation_level: models.PositiveSmallIntegerField[int, int] = models.PositiveSmallIntegerField(
        default=0
    )
    generation: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=1)
    escalation_deadline: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    last_reminded_on: models.DateField[str | date | None, date | None] = models.DateField(
        blank=True,
        null=True,
    )
    creation_idempotency_key: models.CharField[str, str] = models.CharField(
        max_length=128,
        blank=True,
    )
    creation_payload_sha256: models.CharField[str, str] = models.CharField(
        max_length=64,
        blank=True,
    )
    escalation_deferred_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    created_by: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    reason: models.TextField[str, str] = models.TextField(blank=True)
    # 超管创建/认领的单据记 superuser, 豁免 reassign 主管链持续复核(01 §6.1)。
    authority_source: models.CharField[str, str] = models.CharField(
        max_length=32,
        default=AUTHORITY_SOURCE_MANAGER_CHAIN,
        blank=True,
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(kind__in=HANDOVER_KIND_VALUES),
                name="lifecycle_task_kind_supported",
            ),
            models.CheckConstraint(
                condition=Q(status__in=TASK_STATUS_VALUES),
                name="lifecycle_task_status_supported",
            ),
            models.CheckConstraint(
                condition=Q(assignee_state__in=ASSIGNEE_STATE_VALUES),
                name="lifecycle_task_assignee_state_supported",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        assignee_state=ASSIGNEE_STATE_SUPERUSER_POOL,
                        assignee__isnull=True,
                    )
                    | (~Q(assignee_state=ASSIGNEE_STATE_SUPERUSER_POOL) & Q(assignee__isnull=False))
                ),
                name="lifecycle_task_assignee_shape",
            ),
            # reassign 可与其他 open 单并存; 仅约束生命周期类单据一人一张。
            models.UniqueConstraint(
                fields=["subject_user"],
                condition=(
                    Q(status__in=TASK_OPEN_STATUSES)
                    & Q(
                        kind__in=(
                            HANDOVER_KIND_OFFBOARD,
                            HANDOVER_KIND_TRANSFER,
                            HANDOVER_KIND_PRE_OFFBOARD,
                        ),
                    )
                ),
                name="lifecycle_task_one_open_lifecycle_per_subject",
            ),
            models.UniqueConstraint(
                fields=["created_by", "creation_idempotency_key"],
                condition=~Q(creation_idempotency_key=""),
                name="lifecycle_task_creation_idempotency_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]

    @override
    def __str__(self) -> str:
        return f"{self.kind}:{self.subject_user.authentik_user_id}:{self.status}"


class HandoverAppAction(models.Model):
    # 每个 APP 独立交接: 数据接收人下沉到条目级; grant_receiver 仅作权限接收人。
    if TYPE_CHECKING:
        id: ClassVar[int]
        task_id: ClassVar[int]
        app_id: ClassVar[int]
        grant_receiver_id: ClassVar[int | None]

    task: models.ForeignKey[HandoverTask, HandoverTask] = models.ForeignKey(
        HandoverTask,
        on_delete=models.CASCADE,
        related_name="app_actions",
    )
    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.PROTECT,
        related_name="handover_actions",
    )
    app_key_snapshot: models.CharField[str, str] = models.CharField(max_length=64, default="")
    app_name_snapshot: models.CharField[str, str] = models.CharField(max_length=128, default="")
    app_catalog_version_snapshot: models.PositiveIntegerField[int, int] = (
        models.PositiveIntegerField(default=0)
    )
    # 权限接收人(仅 offboard 有意义); 数据接收人在 HandoverAssetType/Override。
    grant_receiver: models.ForeignKey[UserMirror | None, UserMirror | None] = models.ForeignKey(
        UserMirror,
        on_delete=models.PROTECT,
        related_name="handover_grant_receiving",
        blank=True,
        null=True,
    )
    status: models.CharField[str, str] = models.CharField(
        # async_attention_required = 24 chars; 16 会让 E009 与 PG DataError 永久锁租约。
        max_length=32,
        choices=ACTION_STATUS_CHOICES,
        default=ACTION_STATUS_PENDING,
    )
    generation: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=1)
    snapshot_token: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    confirm_version: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    overrides_version: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(
        default=0,
    )
    preview_generation: models.PositiveBigIntegerField[int, int] = models.PositiveBigIntegerField(
        default=0
    )
    batch_seq: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    data_completed_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    blocked_reason: models.CharField[str, str] = models.CharField(max_length=64, blank=True)
    skip_reason: models.TextField[str, str] = models.TextField(blank=True)
    skipped_by: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    skipped_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    approval_instance_warning: models.JSONField[
        dict[str, JsonValue] | None,
        dict[str, JsonValue] | None,
    ] = models.JSONField(blank=True, null=True)
    async_status_url: models.URLField[str, str] = models.URLField(max_length=2048, blank=True)
    async_poll_attempts: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(
        default=0,
    )
    attempts: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    last_error: models.TextField[str, str] = models.TextField(blank=True)
    last_error_raw: models.TextField[str, str] = models.TextField(blank=True)
    # 各批成功 summary 逐字段相加后的展示快照(00 §10.5)。
    result_summary: models.JSONField[
        dict[str, JsonValue] | None,
        dict[str, JsonValue] | None,
    ] = models.JSONField(blank=True, null=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["task", "app"],
                name="lifecycle_action_unique_per_task_app",
            ),
            models.CheckConstraint(
                condition=Q(status__in=ACTION_STATUS_VALUES),
                name="lifecycle_action_status_supported",
            ),
        ]
        ordering: ClassVar[list[str]] = ["task_id", "app__app_key"]

    @override
    def __str__(self) -> str:
        return f"{self.task_id}:{self.app.app_key}:{self.status}"

    @override
    def save(self, *args: object, **kwargs: object) -> None:
        if not self.app_key_snapshot:
            self.app_key_snapshot = self.app.app_key
        if not self.app_name_snapshot:
            self.app_name_snapshot = self.app.name
        if not self.app_catalog_version_snapshot:
            self.app_catalog_version_snapshot = self.app.catalog_version
        super().save(*args, **kwargs)


class ApprovalRuleReplacementRequired(models.Model):
    """§4.5.2: 审批规则替换失败时的持久化待办(规则本身不动)。"""

    if TYPE_CHECKING:
        id: ClassVar[int]
        approval_rule_id: ClassVar[int]
        task_id: ClassVar[int | None]
        departed_user_id: ClassVar[int]

    approval_rule: models.ForeignKey[ApprovalRule, ApprovalRule] = models.ForeignKey(
        "applications.ApprovalRule",
        on_delete=models.CASCADE,
        related_name="replacement_todos",
    )
    task: models.ForeignKey[HandoverTask | None, HandoverTask | None] = models.ForeignKey(
        HandoverTask,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_rule_replacements",
    )
    task_id_snapshot: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    departed_user: models.ForeignKey[UserMirror, UserMirror] = models.ForeignKey(
        UserMirror,
        on_delete=models.PROTECT,
        related_name="approval_rule_replacement_todos",
    )
    reason: models.CharField[str, str] = models.CharField(max_length=64)
    resolved_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    resolved_by: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["approval_rule", "departed_user"],
                condition=Q(resolved_at__isnull=True),
                name="lifecycle_approval_rule_replacement_open_unique",
            ),
        ]

    @override
    def __str__(self) -> str:
        return f"rule-replace:{self.approval_rule_id}:{self.departed_user_id}"


class HandoverActionSkipRecord(models.Model):
    # 强行跳过的永久责任链(append-only); action 上的 skipped_* 在升级时会清空。
    if TYPE_CHECKING:
        id: ClassVar[int]
        task_id: ClassVar[int | None]

    task: models.ForeignKey[HandoverTask | None, HandoverTask | None] = models.ForeignKey(
        HandoverTask,
        on_delete=models.SET_NULL,
        null=True,
        related_name="skip_records",
    )
    task_id_snapshot: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    action_snapshot_id: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    generation: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    app_key: models.CharField[str, str] = models.CharField(max_length=64)
    actor_id: models.CharField[str, str] = models.CharField(max_length=128)
    reason: models.TextField[str, str] = models.TextField()
    skipped_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["task_id_snapshot"], name="lifecycle_skip_task_snap_idx"),
        ]

    @override
    def __str__(self) -> str:
        return f"skip:{self.task_id_snapshot}:{self.action_snapshot_id}:{self.generation}"
