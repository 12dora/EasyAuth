from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar, Final, override

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AuthorizationGroup, Permission
from easyauth.teams.models import Team

if TYPE_CHECKING:
    from datetime import date, datetime

    from easyauth.applications.ops_models import JsonValue

HANDOVER_KIND_OFFBOARD: Final = "offboard"
HANDOVER_KIND_TRANSFER: Final = "transfer"
HANDOVER_KIND_PRE_OFFBOARD: Final = "pre_offboard"
HANDOVER_KIND_REASSIGN: Final = "reassign"
HANDOVER_KIND_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (HANDOVER_KIND_OFFBOARD, "offboard"),
    (HANDOVER_KIND_TRANSFER, "transfer"),
    (HANDOVER_KIND_PRE_OFFBOARD, "pre_offboard"),
    (HANDOVER_KIND_REASSIGN, "reassign"),
)
HANDOVER_KIND_VALUES: Final[tuple[str, ...]] = (
    HANDOVER_KIND_OFFBOARD,
    HANDOVER_KIND_TRANSFER,
    HANDOVER_KIND_PRE_OFFBOARD,
    HANDOVER_KIND_REASSIGN,
)
# 会改动授权的 kind(整单层面); action 执行路径见 ACTION_GRANT_TRANSFER_KINDS。
GRANT_MUTATING_KINDS: Final[tuple[str, ...]] = (HANDOVER_KIND_OFFBOARD, HANDOVER_KIND_TRANSFER)
# action 执行路径是否调用 transfer_selected_grants: 只有 offboard。
ACTION_GRANT_TRANSFER_KINDS: Final[tuple[str, ...]] = (HANDOVER_KIND_OFFBOARD,)

ASSIGNEE_STATE_MANAGER: Final = "manager"
ASSIGNEE_STATE_SUBJECT: Final = "subject"
ASSIGNEE_STATE_SUPERUSER_POOL: Final = "superuser_pool"
ASSIGNEE_STATE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (ASSIGNEE_STATE_MANAGER, "manager"),
    (ASSIGNEE_STATE_SUBJECT, "subject"),
    (ASSIGNEE_STATE_SUPERUSER_POOL, "superuser_pool"),
)
ASSIGNEE_STATE_VALUES: Final[tuple[str, ...]] = (
    ASSIGNEE_STATE_MANAGER,
    ASSIGNEE_STATE_SUBJECT,
    ASSIGNEE_STATE_SUPERUSER_POOL,
)

HANDOVER_ESCALATION_DAYS: Final = 14
LEASE_TTL: Final = timedelta(minutes=5)
LEASE_RENEW_INTERVAL: Final = LEASE_TTL / 3

ONBOARDING_TEMPLATE_REVISION_IMMUTABLE_MESSAGE: Final = (
    "OnboardingTemplateRevision is immutable."
)
ONBOARDING_TEMPLATE_REVISION_ITEM_IMMUTABLE_MESSAGE: Final = (
    "OnboardingTemplateRevisionItem is immutable."
)

TASK_STATUS_PENDING: Final = "pending"
TASK_STATUS_IN_PROGRESS: Final = "in_progress"
TASK_STATUS_COMPLETED: Final = "completed"
TASK_STATUS_CANCELLED: Final = "cancelled"
TASK_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (TASK_STATUS_PENDING, "pending"),
    (TASK_STATUS_IN_PROGRESS, "in_progress"),
    (TASK_STATUS_COMPLETED, "completed"),
    (TASK_STATUS_CANCELLED, "cancelled"),
)
TASK_STATUS_VALUES: Final[tuple[str, ...]] = (
    TASK_STATUS_PENDING,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_CANCELLED,
)
TASK_OPEN_STATUSES: Final[tuple[str, ...]] = (TASK_STATUS_PENDING, TASK_STATUS_IN_PROGRESS)

ACTION_STATUS_PENDING: Final = "pending"
ACTION_STATUS_PREVIEWED: Final = "previewed"
ACTION_STATUS_EXECUTING: Final = "executing"
ACTION_STATUS_ASYNC_PENDING: Final = "async_pending"
ACTION_STATUS_ASYNC_ATTENTION_REQUIRED: Final = "async_attention_required"
ACTION_STATUS_DONE: Final = "done"
ACTION_STATUS_FAILED: Final = "failed"
ACTION_STATUS_SKIPPED: Final = "skipped"
ACTION_STATUS_BLOCKED: Final = "blocked"
ACTION_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (ACTION_STATUS_PENDING, "pending"),
    (ACTION_STATUS_PREVIEWED, "previewed"),
    (ACTION_STATUS_EXECUTING, "executing"),
    (ACTION_STATUS_ASYNC_PENDING, "async_pending"),
    (ACTION_STATUS_ASYNC_ATTENTION_REQUIRED, "async_attention_required"),
    (ACTION_STATUS_DONE, "done"),
    (ACTION_STATUS_FAILED, "failed"),
    (ACTION_STATUS_SKIPPED, "skipped"),
    (ACTION_STATUS_BLOCKED, "blocked"),
)
ACTION_STATUS_VALUES: Final[tuple[str, ...]] = (
    ACTION_STATUS_PENDING,
    ACTION_STATUS_PREVIEWED,
    ACTION_STATUS_EXECUTING,
    ACTION_STATUS_ASYNC_PENDING,
    ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    ACTION_STATUS_DONE,
    ACTION_STATUS_FAILED,
    ACTION_STATUS_SKIPPED,
    ACTION_STATUS_BLOCKED,
)
ACTION_FINISHED_STATUSES: Final[tuple[str, ...]] = (ACTION_STATUS_DONE, ACTION_STATUS_SKIPPED)
# 初始态: 建单后尚未开始执行, 不把 task 推进到 in_progress。
ACTION_INITIAL_STATUSES: Final[tuple[str, ...]] = (
    ACTION_STATUS_PENDING,
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_SKIPPED,
)

ITEM_STATUS_PENDING: Final = "pending"
ITEM_STATUS_DONE: Final = "done"
ITEM_STATUS_SKIPPED: Final = "skipped"
ITEM_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (ITEM_STATUS_PENDING, "pending"),
    (ITEM_STATUS_DONE, "done"),
    (ITEM_STATUS_SKIPPED, "skipped"),
)
ITEM_STATUS_VALUES: Final[tuple[str, ...]] = (
    ITEM_STATUS_PENDING,
    ITEM_STATUS_DONE,
    ITEM_STATUS_SKIPPED,
)

TEAM_ITEM_ACTION_PENDING: Final = "pending"
TEAM_ITEM_ACTION_ASSIGN_LEADER: Final = "assign_leader"
TEAM_ITEM_ACTION_DEACTIVATE: Final = "deactivate"
TEAM_ITEM_ACTION_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (TEAM_ITEM_ACTION_PENDING, "pending"),
    (TEAM_ITEM_ACTION_ASSIGN_LEADER, "assign_leader"),
    (TEAM_ITEM_ACTION_DEACTIVATE, "deactivate"),
)
TEAM_ITEM_ACTION_VALUES: Final[tuple[str, ...]] = (
    TEAM_ITEM_ACTION_PENDING,
    TEAM_ITEM_ACTION_ASSIGN_LEADER,
    TEAM_ITEM_ACTION_DEACTIVATE,
)

ASSET_ACTION_TRANSFER: Final = "transfer"
ASSET_ACTION_RELEASE: Final = "release"
ASSET_ACTION_SKIP: Final = "skip"
ASSET_ACTION_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (ASSET_ACTION_TRANSFER, "transfer"),
    (ASSET_ACTION_RELEASE, "release"),
    (ASSET_ACTION_SKIP, "skip"),
)
ASSET_ACTION_VALUES: Final[tuple[str, ...]] = (
    ASSET_ACTION_TRANSFER,
    ASSET_ACTION_RELEASE,
    ASSET_ACTION_SKIP,
)

BATCH_STATUS_PENDING: Final = "pending"
BATCH_STATUS_EXECUTING: Final = "executing"
BATCH_STATUS_ASYNC_PENDING: Final = "async_pending"
BATCH_STATUS_DATA_COMPLETED: Final = "data_completed"
BATCH_STATUS_DONE: Final = "done"
BATCH_STATUS_FAILED: Final = "failed"
BATCH_STATUS_VALUES: Final[tuple[str, ...]] = (
    BATCH_STATUS_PENDING,
    BATCH_STATUS_EXECUTING,
    BATCH_STATUS_ASYNC_PENDING,
    BATCH_STATUS_DATA_COMPLETED,
    BATCH_STATUS_DONE,
    BATCH_STATUS_FAILED,
)
# §5.5.1 skip/cancel: 仅真正在途; pending(429 重排队)不算 in-flight。
# 改分配端点另用 ASSIGNMENT_MUTATION_IN_FLIGHT_STATUSES(含 pending)。
BATCH_IN_FLIGHT_STATUSES: Final[tuple[str, ...]] = (
    BATCH_STATUS_EXECUTING,
    BATCH_STATUS_ASYNC_PENDING,
)
ASSIGNMENT_MUTATION_IN_FLIGHT_STATUSES: Final[tuple[str, ...]] = (
    BATCH_STATUS_PENDING,
    BATCH_STATUS_EXECUTING,
    BATCH_STATUS_ASYNC_PENDING,
)

DELIVERY_OUTCOME_SENT: Final = "sent"
DELIVERY_OUTCOME_SUCCEEDED: Final = "succeeded"
DELIVERY_OUTCOME_FAILED: Final = "failed"
DELIVERY_OUTCOME_ASYNC_ACCEPTED: Final = "async_accepted"
DELIVERY_OUTCOME_SUPERSEDED: Final = "superseded"
DELIVERY_OUTCOME_VALUES: Final[tuple[str, ...]] = (
    DELIVERY_OUTCOME_SENT,
    DELIVERY_OUTCOME_SUCCEEDED,
    DELIVERY_OUTCOME_FAILED,
    DELIVERY_OUTCOME_ASYNC_ACCEPTED,
    DELIVERY_OUTCOME_SUPERSEDED,
)

BATCH_PLAN_STATUS_ACTIVE: Final = "active"
BATCH_PLAN_STATUS_ABANDONED: Final = "abandoned"
BATCH_PLAN_STATUS_DONE: Final = "done"
BATCH_PLAN_STATUS_VALUES: Final[tuple[str, ...]] = (
    BATCH_PLAN_STATUS_ACTIVE,
    BATCH_PLAN_STATUS_ABANDONED,
    BATCH_PLAN_STATUS_DONE,
)

BLOCKED_REASON_CAPABILITY_UNDECLARED: Final = "capability_undeclared"
BLOCKED_REASON_DESCRIPTOR_UNREACHABLE: Final = "descriptor_unreachable"


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
    escalation_level: models.PositiveSmallIntegerField[int, int] = (
        models.PositiveSmallIntegerField(default=0)
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
                    | (
                        ~Q(assignee_state=ASSIGNEE_STATE_SUPERUSER_POOL)
                        & Q(assignee__isnull=False)
                    )
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
    preview_generation: models.PositiveBigIntegerField[int, int] = (
        models.PositiveBigIntegerField(default=0)
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


class HandoverAssetType(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        action_id: ClassVar[int]
        default_to_user_id: ClassVar[int | None]

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


class HandoverExecutionLease(models.Model):
    # (subject, app) 维度执行互斥租约; 条件唯一约束保证同时只有一条 active。
    if TYPE_CHECKING:
        id: ClassVar[int]
        subject_user_id: ClassVar[int]
        app_id: ClassVar[int]
        action_id: ClassVar[int]

    subject_user: models.ForeignKey[UserMirror, UserMirror] = models.ForeignKey(
        UserMirror,
        on_delete=models.PROTECT,
        related_name="handover_leases",
    )
    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.PROTECT,
        related_name="handover_leases",
    )
    action: models.ForeignKey[HandoverAppAction, HandoverAppAction] = models.ForeignKey(
        HandoverAppAction,
        on_delete=models.CASCADE,
        related_name="leases",
    )
    generation: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    batch_seq: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    owner: models.CharField[str, str] = models.CharField(max_length=128)
    fence: models.PositiveBigIntegerField[int, int] = models.PositiveBigIntegerField()
    acquired_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    lease_expires_at: models.DateTimeField[str | date | datetime, datetime] = (
        models.DateTimeField()
    )
    renewed_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    released_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["subject_user", "app"],
                condition=Q(released_at__isnull=True),
                name="lifecycle_lease_one_active_per_subject_app",
            ),
        ]

    @override
    def __str__(self) -> str:
        return f"lease:{self.subject_user_id}:{self.app_id}:f{self.fence}"


class HandoverLeaseFence(models.Model):
    """(subject_user, app) 维度的 fence 取号器, 与租约行分开, 永不删除。"""

    if TYPE_CHECKING:
        id: ClassVar[int]
        subject_user_id: ClassVar[int]
        app_id: ClassVar[int]

    subject_user: models.ForeignKey[UserMirror, UserMirror] = models.ForeignKey(
        UserMirror,
        on_delete=models.PROTECT,
    )
    app: models.ForeignKey[App, App] = models.ForeignKey(App, on_delete=models.PROTECT)
    next_fence: models.PositiveBigIntegerField[int, int] = models.PositiveBigIntegerField(
        default=1,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["subject_user", "app"],
                name="lifecycle_fence_unique",
            ),
        ]

    @override
    def __str__(self) -> str:
        return f"fence:{self.subject_user_id}:{self.app_id}:{self.next_fence}"


class HandoverGrantItem(models.Model):
    # 建单时对当事人现有授权(current 行, 含刚被撤销的)做快照;
    # 向导按快照逐条勾选转移, 默认全选(§7 决策 12)。
    if TYPE_CHECKING:
        id: ClassVar[int]
        task_id: ClassVar[int]
        app_id: ClassVar[int]

    task: models.ForeignKey[HandoverTask, HandoverTask] = models.ForeignKey(
        HandoverTask,
        on_delete=models.CASCADE,
        related_name="grant_items",
    )
    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.PROTECT,
        related_name="handover_grant_items",
    )
    generation: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=1)
    app_key_snapshot: models.CharField[str, str] = models.CharField(max_length=64, default="")
    app_name_snapshot: models.CharField[str, str] = models.CharField(max_length=128, default="")
    app_catalog_version_snapshot: models.PositiveIntegerField[int, int] = (
        models.PositiveIntegerField(default=0)
    )
    authorization_group: models.ForeignKey[
        AuthorizationGroup | None,
        AuthorizationGroup | None,
    ] = models.ForeignKey(
        AuthorizationGroup,
        on_delete=models.SET_NULL,
        related_name="handover_grant_items",
        blank=True,
        null=True,
    )
    permission: models.ForeignKey[Permission | None, Permission | None] = models.ForeignKey(
        Permission,
        on_delete=models.SET_NULL,
        related_name="handover_grant_items",
        blank=True,
        null=True,
    )
    scope_key: models.CharField[str, str] = models.CharField(max_length=64, blank=True)
    target_kind_snapshot: models.CharField[str, str] = models.CharField(max_length=16, default="")
    target_key_snapshot: models.CharField[str, str] = models.CharField(max_length=128, default="")
    target_name_snapshot: models.CharField[str, str] = models.CharField(max_length=128, default="")
    source_grant_id: models.PositiveBigIntegerField[int, int] = models.PositiveBigIntegerField(
        default=0,
    )
    source_grant_version: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(
        default=0,
    )
    grant_type: models.CharField[str, str] = models.CharField(max_length=16, blank=True)
    grant_expires_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    selected: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    status: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=ITEM_STATUS_CHOICES,
        default=ITEM_STATUS_PENDING,
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(status__in=ITEM_STATUS_VALUES),
                name="lifecycle_grant_item_status_supported",
            ),
            models.CheckConstraint(
                condition=Q(target_kind_snapshot__in=("group", "permission")),
                name="lifecycle_grant_item_target_shape",
            ),
            models.UniqueConstraint(
                fields=[
                    "task",
                    "generation",
                    "source_grant_id",
                    "target_kind_snapshot",
                    "target_key_snapshot",
                    "scope_key",
                ],
                name="lifecycle_grant_item_unique_per_generation",
            ),
        ]
        ordering: ClassVar[list[str]] = ["task_id", "app__app_key", "id"]

    @override
    def __str__(self) -> str:
        return f"{self.task_id}:{self.app.app_key}:{self.id}"

    @override
    def clean(self) -> None:
        super().clean()
        if self.target_kind_snapshot not in {"group", "permission"}:
            raise ValidationError(
                {"target_kind_snapshot": "Grant item target kind is invalid."},
            )


class HandoverTeamItem(models.Model):
    # leader 离职时其领导的团队列入交接单: 接收人接任 leader 或团队停用(§4.5)。
    if TYPE_CHECKING:
        id: ClassVar[int]
        task_id: ClassVar[int]
        team_id: ClassVar[int]

    task: models.ForeignKey[HandoverTask, HandoverTask] = models.ForeignKey(
        HandoverTask,
        on_delete=models.CASCADE,
        related_name="team_items",
    )
    team: models.ForeignKey[Team, Team] = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="handover_items",
    )
    action: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=TEAM_ITEM_ACTION_CHOICES,
        default=TEAM_ITEM_ACTION_PENDING,
    )
    to_user: models.ForeignKey[UserMirror | None, UserMirror | None] = models.ForeignKey(
        UserMirror,
        on_delete=models.PROTECT,
        related_name="handover_team_items",
        blank=True,
        null=True,
    )
    status: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=ITEM_STATUS_CHOICES,
        default=ITEM_STATUS_PENDING,
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["task", "team"],
                name="lifecycle_team_item_unique",
            ),
            models.CheckConstraint(
                condition=Q(action__in=TEAM_ITEM_ACTION_VALUES),
                name="lifecycle_team_item_action_supported",
            ),
        ]
        ordering: ClassVar[list[str]] = ["task_id", "team__name"]

    @override
    def __str__(self) -> str:
        return f"{self.task_id}:{self.team.name}:{self.action}"


class OnboardingTemplate(models.Model):
    # 岗位模板: 一键入职与转岗差异计算的授权基准。
    if TYPE_CHECKING:
        id: ClassVar[int]

    name: models.CharField[str, str] = models.CharField(max_length=128, unique=True)
    description: models.TextField[str, str] = models.TextField(blank=True)
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )
    current_revision: models.ForeignKey[
        OnboardingTemplateRevision | None,
        OnboardingTemplateRevision | None,
    ] = models.ForeignKey(
        "OnboardingTemplateRevision",
        on_delete=models.PROTECT,
        related_name="+",
        blank=True,
        null=True,
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["name"]

    @override
    def __str__(self) -> str:
        return self.name


class OnboardingTemplateRevision(models.Model):
    # 模板修订: 编辑岗位模板只产生新修订; 已被转岗计划绑定的修订保持不可变。
    if TYPE_CHECKING:
        id: ClassVar[int]
        template_id: ClassVar[int]

    template: models.ForeignKey[OnboardingTemplate, OnboardingTemplate] = models.ForeignKey(
        OnboardingTemplate,
        on_delete=models.CASCADE,
        related_name="revisions",
    )
    revision: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    name_snapshot: models.CharField[str, str] = models.CharField(max_length=128)
    description_snapshot: models.TextField[str, str] = models.TextField(blank=True)
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["template", "revision"],
                name="lifecycle_template_revision_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["template_id", "-revision"]

    @override
    def __str__(self) -> str:
        return f"{self.template_id}:r{self.revision}"

    @override
    def save(self, *args: object, **kwargs: object) -> None:
        if not self._state.adding:
            raise ValidationError(ONBOARDING_TEMPLATE_REVISION_IMMUTABLE_MESSAGE)
        super().save(*args, **kwargs)

    @override
    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise ValidationError(ONBOARDING_TEMPLATE_REVISION_IMMUTABLE_MESSAGE)


class OnboardingTemplateRevisionItem(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        revision_id: ClassVar[int]
        app_id: ClassVar[int]

    revision: models.ForeignKey[
        OnboardingTemplateRevision,
        OnboardingTemplateRevision,
    ] = models.ForeignKey(
        OnboardingTemplateRevision,
        on_delete=models.CASCADE,
        related_name="items",
    )
    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="onboarding_template_items",
    )
    authorization_group: models.ForeignKey[
        AuthorizationGroup | None,
        AuthorizationGroup | None,
    ] = models.ForeignKey(
        AuthorizationGroup,
        on_delete=models.CASCADE,
        related_name="onboarding_template_items",
        blank=True,
        null=True,
    )
    permission: models.ForeignKey[Permission | None, Permission | None] = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name="onboarding_template_items",
        blank=True,
        null=True,
    )
    scope_key: models.CharField[str, str] = models.CharField(max_length=64, blank=True)
    grant_type: models.CharField[str, str] = models.CharField(max_length=16, default="permanent")
    duration_days: models.PositiveIntegerField[int | None, int | None] = (
        models.PositiveIntegerField(blank=True, null=True)
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=(
                    Q(authorization_group__isnull=False, permission__isnull=True)
                    | Q(authorization_group__isnull=True, permission__isnull=False)
                ),
                name="lifecycle_template_revision_item_target_shape",
            ),
            models.CheckConstraint(
                condition=(
                    Q(grant_type="permanent", duration_days__isnull=True)
                    | Q(grant_type="timed", duration_days__isnull=False)
                ),
                name="lifecycle_template_revision_item_expiration_shape",
            ),
        ]
        ordering: ClassVar[list[str]] = ["revision_id", "app__app_key", "id"]

    @override
    def __str__(self) -> str:
        return f"{self.revision_id}:{self.app.app_key}:{self.id}"

    @override
    def save(self, *args: object, **kwargs: object) -> None:
        if not self._state.adding:
            raise ValidationError(ONBOARDING_TEMPLATE_REVISION_ITEM_IMMUTABLE_MESSAGE)
        super().save(*args, **kwargs)

    @override
    def delete(self, *args: object, **kwargs: object) -> tuple[int, dict[str, int]]:
        raise ValidationError(ONBOARDING_TEMPLATE_REVISION_ITEM_IMMUTABLE_MESSAGE)

    @override
    def clean(self) -> None:
        super().clean()
        has_group = self.authorization_group is not None
        has_permission = self.permission is not None
        if has_group == has_permission:
            raise ValidationError(
                {"authorization_group": "Template item must target a group or a permission."},
            )
        if self.grant_type == "timed" and not self.duration_days:
            raise ValidationError({"duration_days": "Timed template items need duration_days."})
        if self.grant_type == "permanent" and self.duration_days is not None:
            raise ValidationError(
                {"duration_days": "Permanent template items cannot include duration_days."},
            )
        if self.grant_type not in {"permanent", "timed"}:
            raise ValidationError({"grant_type": "Template item grant type is invalid."})


class TransferPlan(models.Model):
    # kind=transfer 专用: 新岗位模板与授权差异清单(确认时逐条可勾选)。
    if TYPE_CHECKING:
        id: ClassVar[int]
        task_id: ClassVar[int]
        new_template_revision_id: ClassVar[int | None]

    task: models.OneToOneField[HandoverTask, HandoverTask] = models.OneToOneField(
        HandoverTask,
        on_delete=models.CASCADE,
        related_name="transfer_plan",
    )
    new_template: models.ForeignKey[
        OnboardingTemplate | None,
        OnboardingTemplate | None,
    ] = models.ForeignKey(
        OnboardingTemplate,
        on_delete=models.PROTECT,
        related_name="transfer_plans",
        blank=True,
        null=True,
    )
    new_template_revision: models.ForeignKey[
        OnboardingTemplateRevision | None,
        OnboardingTemplateRevision | None,
    ] = models.ForeignKey(
        OnboardingTemplateRevision,
        on_delete=models.PROTECT,
        related_name="transfer_plans",
        blank=True,
        null=True,
    )
    grant_diff: models.JSONField[dict[str, JsonValue], dict[str, JsonValue]] = models.JSONField(
        default=dict,
        blank=True,
    )
    revision: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    confirmed_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    confirmed_revoke_keys: models.JSONField[list[str], list[str]] = models.JSONField(
        default=list,
        blank=True,
    )
    confirmed_add_keys: models.JSONField[list[str], list[str]] = models.JSONField(
        default=list,
        blank=True,
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    @override
    def __str__(self) -> str:
        return f"transfer-plan:{self.task_id}"
