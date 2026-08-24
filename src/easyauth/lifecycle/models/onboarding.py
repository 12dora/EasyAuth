"""定义入职模板, 不可变修订版本及其授权条目模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, override

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from easyauth.applications.models import App, AuthorizationGroup, Permission

from .constants import (
    ONBOARDING_TEMPLATE_REVISION_IMMUTABLE_MESSAGE,
    ONBOARDING_TEMPLATE_REVISION_ITEM_IMMUTABLE_MESSAGE,
)

if TYPE_CHECKING:
    from datetime import date, datetime


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
