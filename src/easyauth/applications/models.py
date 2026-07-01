from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar, override

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .approval_rule_rules import approval_rule_clean_errors
from .oauth_models import OAuthClientBinding
from .ops_models import (
    AppMembership,
    AuthorizationGroupAccessPolicy,
    PermissionGroup,
    PermissionTemplateVersion,
    RoleAccessPolicy,
)

__all__ = (
    "App",
    "AppCredential",
    "AppMembership",
    "AppScope",
    "AppStaticToken",
    "ApprovalRule",
    "AuthorizationGroup",
    "AuthorizationGroupAccessPolicy",
    "AuthorizationGroupGrant",
    "OAuthClientBinding",
    "Permission",
    "PermissionGroup",
    "PermissionTemplateVersion",
    "Role",
    "RoleAccessPolicy",
    "RolePermission",
)

if TYPE_CHECKING:
    from datetime import date, datetime

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]

APP_SCOPE_KEY_PATTERN = re.compile(r"^[A-Z0-9_]+$")
AUTHORIZATION_GROUP_KINDS = ("role", "bundle")
PERMISSION_RISK_LEVELS = ("standard", "high")


class App(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        app_id: ClassVar[int]

    app_key: models.CharField[str, str] = models.CharField(max_length=64, unique=True)
    name: models.CharField[str, str] = models.CharField(max_length=128)
    description: models.TextField[str, str] = models.TextField(blank=True)
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    catalog_version: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=1)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["app_key"]

    @override
    def __str__(self) -> str:
        return self.app_key


class AppCredential(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]

    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="credentials",
    )
    credential_type: models.CharField[str, str] = models.CharField(max_length=32)
    name: models.CharField[str, str] = models.CharField(max_length=128)
    token_hash: models.CharField[str, str] = models.CharField(max_length=256)
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    disabled_at: models.DateTimeField[str | date | datetime | None, datetime | None] = (
        models.DateTimeField(blank=True, null=True)
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["app__app_key", "credential_type", "id"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.credential_type}:{self.id}"


AppStaticToken = AppCredential


class AppScope(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        app_id: ClassVar[int]

    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="scopes",
    )
    key: models.CharField[str, str] = models.CharField(max_length=64)
    name: models.CharField[str, str] = models.CharField(max_length=128)
    description: models.TextField[str, str] = models.TextField(blank=True)
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    display_order: models.IntegerField[int, int] = models.IntegerField(default=0)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["app", "key"],
                name="applications_app_scope_app_key_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["app__app_key", "display_order", "key"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.key}"

    @override
    def clean(self) -> None:
        super().clean()
        if not APP_SCOPE_KEY_PATTERN.fullmatch(self.key):
            raise ValidationError(
                {
                    "key": (
                        "App scope key must contain only uppercase letters, digits, "
                        "or underscores."
                    ),
                },
            )


class Role(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        app_id: ClassVar[int]

    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="roles",
    )
    key: models.CharField[str, str] = models.CharField(max_length=64)
    name: models.CharField[str, str] = models.CharField(max_length=128)
    description: models.TextField[str, str] = models.TextField(blank=True)
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    requestable: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["app", "key"],
                name="applications_role_app_key_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["app__app_key", "key"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.key}"


class Permission(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        app_id: ClassVar[int]

    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="permissions",
    )
    group: models.ForeignKey[PermissionGroup | None, PermissionGroup | None] = (
        models.ForeignKey(
            "applications.PermissionGroup",
            on_delete=models.SET_NULL,
            related_name="permissions",
            blank=True,
            null=True,
        )
    )
    key: models.CharField[str, str] = models.CharField(max_length=128)
    name: models.CharField[str, str] = models.CharField(max_length=128)
    description: models.TextField[str, str] = models.TextField(blank=True)
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    supported_scopes: models.JSONField[JsonValue, JsonValue] = models.JSONField(
        blank=True,
        default=list,
    )
    risk_level: models.CharField[str, str] = models.CharField(max_length=32, default="standard")
    deprecated_at: models.DateTimeField[str | date | datetime | None, datetime | None] = (
        models.DateTimeField(blank=True, null=True)
    )
    deprecated_reason: models.TextField[str, str] = models.TextField(blank=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["app", "key"],
                name="applications_permission_app_key_unique",
            ),
            models.CheckConstraint(
                condition=Q(risk_level__in=PERMISSION_RISK_LEVELS),
                name="applications_permission_risk_level_supported",
            ),
        ]
        ordering: ClassVar[list[str]] = ["app__app_key", "key"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.key}"

    @override
    def clean(self) -> None:
        super().clean()
        group = self.group
        if group is not None and group.app_id != self.app_id:
            raise ValidationError({"group": "Permission group must belong to the same app."})
        errors: dict[str, str] = {}
        if self.risk_level not in PERMISSION_RISK_LEVELS:
            errors["risk_level"] = "Permission risk level must be standard or high."
        if self.is_active and not self.supported_scopes:
            errors["supported_scopes"] = "Active permission must support at least one scope."
        if errors:
            raise ValidationError(errors)


class AuthorizationGroup(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        app_id: ClassVar[int]

    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="authorization_groups",
    )
    key: models.CharField[str, str] = models.CharField(max_length=64)
    kind: models.CharField[str, str] = models.CharField(max_length=32)
    name: models.CharField[str, str] = models.CharField(max_length=128)
    description: models.TextField[str, str] = models.TextField(blank=True)
    requestable: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["app", "key"],
                name="applications_authorization_group_app_key_unique",
            ),
            models.CheckConstraint(
                condition=Q(kind__in=AUTHORIZATION_GROUP_KINDS),
                name="applications_authorization_group_kind_supported",
            ),
        ]
        ordering: ClassVar[list[str]] = ["app__app_key", "kind", "key"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.key}"

    @override
    def clean(self) -> None:
        super().clean()
        if self.kind not in AUTHORIZATION_GROUP_KINDS:
            raise ValidationError({"kind": "Authorization group kind must be role or bundle."})


class AuthorizationGroupGrant(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        authorization_group_id: ClassVar[int]
        permission_id: ClassVar[int]

    authorization_group: models.ForeignKey[AuthorizationGroup, AuthorizationGroup] = (
        models.ForeignKey(
            AuthorizationGroup,
            on_delete=models.CASCADE,
            related_name="grants",
        )
    )
    permission: models.ForeignKey[Permission, Permission] = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name="authorization_group_grants",
    )
    scope_key: models.CharField[str, str] = models.CharField(max_length=64)
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["authorization_group", "permission", "scope_key"],
                name="applications_authorization_group_grant_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = [
            "authorization_group__app__app_key",
            "authorization_group__key",
            "permission__key",
            "scope_key",
        ]

    @override
    def __str__(self) -> str:
        return f"{self.authorization_group} -> {self.permission}:{self.scope_key}"

    @override
    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        app_id = self.authorization_group.app_id
        if self.permission.app_id != app_id:
            errors["permission"] = "Permission must belong to the authorization group app."
        elif not AppScope.objects.filter(app_id=app_id, key=self.scope_key).exists():
            errors["scope_key"] = "Scope key must reference an app scope."
        elif self.scope_key not in self.permission.supported_scopes:
            errors["scope_key"] = "Scope key must be supported by the permission."
        if errors:
            raise ValidationError(errors)


class RolePermission(models.Model):
    if TYPE_CHECKING:
        role_id: ClassVar[int]
        permission_id: ClassVar[int]

    role: models.ForeignKey[Role, Role] = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )
    permission: models.ForeignKey[Permission, Permission] = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["role", "permission"],
                name="applications_role_permission_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["role__app__app_key", "role__key", "permission__key"]

    @override
    def __str__(self) -> str:
        return f"{self.role} -> {self.permission}"

    @override
    def clean(self) -> None:
        super().clean()
        if self.role.app != self.permission.app:
            raise ValidationError(
                {"permission": "Role and permission must belong to the same app."},
            )


class ApprovalRule(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]

    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="approval_rules",
    )
    role: models.ForeignKey[Role | None, Role | None] = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="approval_rules",
        blank=True,
        null=True,
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
                        role__isnull=True,
                        authorization_group__isnull=False,
                        permission__isnull=True,
                    )
                    | Q(
                        role__isnull=True,
                        authorization_group__isnull=True,
                        permission__isnull=False,
                    )
                ),
                name="applications_approval_rule_one_target",
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
