"""定义转岗任务绑定的模板与授权差异计划模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, override

from django.db import models

from .onboarding import OnboardingTemplate, OnboardingTemplateRevision
from .task import HandoverTask

if TYPE_CHECKING:
    from datetime import date, datetime

    from easyauth.applications.ops_models import JsonValue


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
