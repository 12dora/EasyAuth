from __future__ import annotations

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
HANDOVER_KIND_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (HANDOVER_KIND_OFFBOARD, "offboard"),
    (HANDOVER_KIND_TRANSFER, "transfer"),
)
HANDOVER_KIND_VALUES: Final[tuple[str, ...]] = (
    HANDOVER_KIND_OFFBOARD,
    HANDOVER_KIND_TRANSFER,
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
ACTION_STATUS_DONE: Final = "done"
ACTION_STATUS_FAILED: Final = "failed"
ACTION_STATUS_SKIPPED: Final = "skipped"
ACTION_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (ACTION_STATUS_PENDING, "pending"),
    (ACTION_STATUS_PREVIEWED, "previewed"),
    (ACTION_STATUS_EXECUTING, "executing"),
    (ACTION_STATUS_DONE, "done"),
    (ACTION_STATUS_FAILED, "failed"),
    (ACTION_STATUS_SKIPPED, "skipped"),
)
ACTION_STATUS_VALUES: Final[tuple[str, ...]] = (
    ACTION_STATUS_PENDING,
    ACTION_STATUS_PREVIEWED,
    ACTION_STATUS_EXECUTING,
    ACTION_STATUS_DONE,
    ACTION_STATUS_FAILED,
    ACTION_STATUS_SKIPPED,
)
ACTION_FINISHED_STATUSES: Final[tuple[str, ...]] = (ACTION_STATUS_DONE, ACTION_STATUS_SKIPPED)

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


class HandoverTask(models.Model):
    # 交接单: 离职单由目录同步自动创建, 管理员可手动建单(含在职员工提前交接与转岗)。
    # 缓冲是常态: 无接收人时停在 pending/in_progress, 无期限, 数据原地保留。
    if TYPE_CHECKING:
        id: ClassVar[int]
        subject_user_id: ClassVar[int]

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
            # 同一当事人同一时刻只允许一张进行中的交接单; 已取消的可重新建单。
            models.UniqueConstraint(
                fields=["subject_user"],
                condition=Q(status__in=TASK_OPEN_STATUSES),
                name="lifecycle_task_one_open_per_subject",
            ),
        ]
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]

    @override
    def __str__(self) -> str:
        return f"{self.kind}:{self.subject_user.authentik_user_id}:{self.status}"


class HandoverAppAction(models.Model):
    # 每个 APP 独立交接: 各自指定接收人、独立 preview/execute, 互不阻塞。
    if TYPE_CHECKING:
        id: ClassVar[int]
        task_id: ClassVar[int]
        app_id: ClassVar[int]

    task: models.ForeignKey[HandoverTask, HandoverTask] = models.ForeignKey(
        HandoverTask,
        on_delete=models.CASCADE,
        related_name="app_actions",
    )
    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="handover_actions",
    )
    to_user: models.ForeignKey[UserMirror | None, UserMirror | None] = models.ForeignKey(
        UserMirror,
        on_delete=models.PROTECT,
        related_name="handover_receiving_actions",
        blank=True,
        null=True,
    )
    policy: models.JSONField[dict[str, JsonValue], dict[str, JsonValue]] = models.JSONField(
        default=dict,
        blank=True,
    )
    status: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=ACTION_STATUS_CHOICES,
        default=ACTION_STATUS_PENDING,
    )
    preview_payload: models.JSONField[
        dict[str, JsonValue],
        dict[str, JsonValue],
    ] = models.JSONField(default=dict, blank=True)
    result_payload: models.JSONField[
        dict[str, JsonValue],
        dict[str, JsonValue],
    ] = models.JSONField(default=dict, blank=True)
    attempts: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    last_error: models.TextField[str, str] = models.TextField(blank=True)
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
        on_delete=models.CASCADE,
        related_name="handover_grant_items",
    )
    authorization_group: models.ForeignKey[
        AuthorizationGroup | None,
        AuthorizationGroup | None,
    ] = models.ForeignKey(
        AuthorizationGroup,
        on_delete=models.CASCADE,
        related_name="handover_grant_items",
        blank=True,
        null=True,
    )
    permission: models.ForeignKey[Permission | None, Permission | None] = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name="handover_grant_items",
        blank=True,
        null=True,
    )
    scope_key: models.CharField[str, str] = models.CharField(max_length=64, blank=True)
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
            # 快照条目必须指向授权组或(权限+范围)其一。
            models.CheckConstraint(
                condition=(
                    Q(authorization_group__isnull=False, permission__isnull=True)
                    | Q(authorization_group__isnull=True, permission__isnull=False)
                ),
                name="lifecycle_grant_item_target_shape",
            ),
        ]
        ordering: ClassVar[list[str]] = ["task_id", "app__app_key", "id"]

    @override
    def __str__(self) -> str:
        return f"{self.task_id}:{self.app.app_key}:{self.id}"

    @override
    def clean(self) -> None:
        super().clean()
        has_group = self.authorization_group is not None
        has_permission = self.permission is not None
        if has_group == has_permission:
            raise ValidationError(
                {"authorization_group": "Grant item must target a group or a permission."},
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

    class Meta:
        ordering: ClassVar[list[str]] = ["name"]

    @override
    def __str__(self) -> str:
        return self.name


class OnboardingTemplateItem(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        template_id: ClassVar[int]
        app_id: ClassVar[int]

    template: models.ForeignKey[OnboardingTemplate, OnboardingTemplate] = models.ForeignKey(
        OnboardingTemplate,
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
                name="lifecycle_template_item_target_shape",
            ),
        ]
        ordering: ClassVar[list[str]] = ["template_id", "app__app_key", "id"]

    @override
    def __str__(self) -> str:
        return f"{self.template_id}:{self.app.app_key}:{self.id}"

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


class TransferPlan(models.Model):
    # kind=transfer 专用: 新岗位模板与授权差异清单(确认时逐条可勾选)。
    if TYPE_CHECKING:
        id: ClassVar[int]
        task_id: ClassVar[int]

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
    grant_diff: models.JSONField[dict[str, JsonValue], dict[str, JsonValue]] = models.JSONField(
        default=dict,
        blank=True,
    )
    confirmed_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    @override
    def __str__(self) -> str:
        return f"transfer-plan:{self.task_id}"
