"""定义 managed scope 策略模型及其目标约束。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast, override

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .app import App
from .catalog import AuthorizationGroupGrant
from .constants import (
    MANAGED_SCOPE_POLICY_RESOLVERS,
    MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
    MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
    MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
    MANAGED_SCOPE_POLICY_TARGET_TYPES,
)

if TYPE_CHECKING:
    from datetime import date, datetime


class ManagedScopePolicy(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        app_id: ClassVar[int]

    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="managed_scope_policies",
    )
    target_type: models.CharField[str, str] = models.CharField(max_length=64)
    authorization_group_grant: models.ForeignKey[
        AuthorizationGroupGrant | None,
        AuthorizationGroupGrant | None,
    ] = models.ForeignKey(
        AuthorizationGroupGrant,
        on_delete=models.CASCADE,
        related_name="managed_scope_policies",
        blank=True,
        null=True,
    )
    scope: models.CharField[str, str] = models.CharField(max_length=64)
    resolver: models.CharField[str, str] = models.CharField(max_length=64)
    enabled: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["app", "target_type", "scope"],
                condition=Q(target_type=MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT),
                name="applications_managed_scope_policy_app_default_unique",
            ),
            models.UniqueConstraint(
                fields=["authorization_group_grant", "scope"],
                condition=Q(
                    target_type=MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
                ),
                name="applications_managed_scope_policy_grant_unique",
            ),
            models.CheckConstraint(
                condition=Q(target_type__in=MANAGED_SCOPE_POLICY_TARGET_TYPES),
                name="applications_managed_scope_policy_target_type_supported",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        target_type=MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
                        authorization_group_grant__isnull=True,
                    )
                    | Q(
                        target_type=MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
                        authorization_group_grant__isnull=False,
                    )
                ),
                name="applications_managed_scope_policy_target_shape",
            ),
            models.CheckConstraint(
                condition=Q(scope=MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS),
                name="applications_managed_scope_policy_scope_managed_users",
            ),
            models.CheckConstraint(
                condition=Q(resolver__in=MANAGED_SCOPE_POLICY_RESOLVERS),
                name="applications_managed_scope_policy_resolver_supported",
            ),
        ]
        ordering: ClassVar[list[str]] = [
            "app__app_key",
            "target_type",
            "authorization_group_grant_id",
            "scope",
        ]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.target_type}:{self.target_id}:{self.scope}"

    @property
    def target_id(self) -> int:
        if self.target_type == MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT:
            return self.app_id
        grant = self.authorization_group_grant
        if grant is None:
            return 0
        return cast("int", grant.pk)

    @override
    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.target_type not in MANAGED_SCOPE_POLICY_TARGET_TYPES:
            errors["target_type"] = (
                "Managed scope policy target type must be app_default or authorization_group_grant."
            )
        elif self.target_type == MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT:
            if self.authorization_group_grant is not None:
                errors["authorization_group_grant"] = (
                    "App default policy must not reference an authorization group grant."
                )
        else:
            grant = self.authorization_group_grant
            if grant is None:
                errors["authorization_group_grant"] = "Authorization group grant target must exist."
            elif grant.authorization_group.app_id != self.app_id:
                errors["authorization_group_grant"] = (
                    "Authorization group grant target must belong to the same app."
                )
        if self.scope != MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS:
            errors["scope"] = "Managed scope policy scope must be MANAGED_USERS."
        if self.resolver not in MANAGED_SCOPE_POLICY_RESOLVERS:
            errors["resolver"] = (
                "Managed scope policy resolver must be one of "
                "dingtalk_manager_chain, easyauth_team, union, disabled."
            )
        if errors:
            raise ValidationError(errors)
