"""定义交接执行租约及其单调递增的 fence 取号模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, override

from django.db import models
from django.db.models import Q

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App

from .task import HandoverAppAction

if TYPE_CHECKING:
    from datetime import date, datetime


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
    lease_expires_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField()
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
