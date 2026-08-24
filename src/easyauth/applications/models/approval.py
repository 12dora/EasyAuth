"""定义面向授权组与权限目标的审批规则模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, override

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from easyauth.applications.approval_rule_rules import approval_rule_clean_errors

from .app import App
from .catalog import AuthorizationGroup, Permission

if TYPE_CHECKING:
    from datetime import date, datetime

    from .constants import JsonValue


class ApprovalRule(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        authorization_group_id: ClassVar[int | None]
        permission_id: ClassVar[int | None]

    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="approval_rules",
    )
    authorization_group: models.ForeignKey[
        AuthorizationGroup | None,
        AuthorizationGroup | None,
    ] = models.ForeignKey(
        AuthorizationGroup,
        on_delete=models.CASCADE,
        related_name="approval_rules",
        blank=True,
        null=True,
    )
    permission: models.ForeignKey[Permission | None, Permission | None] = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name="approval_rules",
        blank=True,
        null=True,
    )
    approver_userids: models.JSONField[JsonValue, JsonValue] = models.JSONField(default=list)
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=(
                    Q(
                        authorization_group__isnull=False,
                        permission__isnull=True,
                    )
                    | Q(
                        authorization_group__isnull=True,
                        permission__isnull=False,
                    )
                ),
                name="applications_approval_rule_one_target",
            ),
            # 同一目标只允许一条审批规则; 否则清单导入(取最大 id)和审批解析(取最小 id)
            # 会读写不同的行, 导入成功却路由到已移除的旧审批人。
            models.UniqueConstraint(
                fields=["app", "authorization_group"],
                condition=Q(authorization_group__isnull=False),
                name="applications_approval_rule_group_unique",
            ),
            models.UniqueConstraint(
                fields=["app", "permission"],
                condition=Q(permission__isnull=False),
                name="applications_approval_rule_permission_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["app__app_key", "id"]

    @override
    def __str__(self) -> str:
        authorization_group = self.authorization_group
        permission = self.permission
        target_key = "unbound"
        if authorization_group is not None:
            target_key = authorization_group.key
        if permission is not None:
            target_key = permission.key
        return f"{self.app.app_key}:{target_key}"

    @override
    def clean(self) -> None:
        super().clean()
        errors = approval_rule_clean_errors(self)
        if errors:
            raise ValidationError(errors)
