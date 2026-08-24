"""定义交接授权快照项与团队处置项模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, override

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AuthorizationGroup, Permission
from easyauth.teams.models import Team

from .constants import (
    ITEM_STATUS_CHOICES,
    ITEM_STATUS_PENDING,
    ITEM_STATUS_VALUES,
    TEAM_ITEM_ACTION_CHOICES,
    TEAM_ITEM_ACTION_PENDING,
    TEAM_ITEM_ACTION_VALUES,
)
from .task import HandoverTask

if TYPE_CHECKING:
    from datetime import date, datetime


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
