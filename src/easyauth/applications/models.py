from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, override

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from easyauth.applications import oauth_models

OAuthClientBinding = oauth_models.OAuthClientBinding

if TYPE_CHECKING:
    from datetime import date, datetime

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


class App(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]

    app_key: models.CharField[str, str] = models.CharField(max_length=64, unique=True)
    name: models.CharField[str, str] = models.CharField(max_length=128)
    description: models.TextField[str, str] = models.TextField(blank=True)
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
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


class Role(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]

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
    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="permissions",
    )
    key: models.CharField[str, str] = models.CharField(max_length=128)
    name: models.CharField[str, str] = models.CharField(max_length=128)
    description: models.TextField[str, str] = models.TextField(blank=True)
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
                name="applications_permission_app_key_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["app__app_key", "key"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.key}"


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
                    Q(role__isnull=False, permission__isnull=True)
                    | Q(role__isnull=True, permission__isnull=False)
                ),
                name="applications_approval_rule_one_target",
            ),
        ]
        ordering: ClassVar[list[str]] = ["app__app_key", "id"]

    @override
    def __str__(self) -> str:
        role = self.role
        permission = self.permission
        target_key = "unbound"
        if role is not None:
            target_key = role.key
        if permission is not None:
            target_key = permission.key
        return f"{self.app.app_key}:{target_key}"

    @override
    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        role = self.role
        permission = self.permission
        has_role = role is not None
        has_permission = permission is not None

        if has_role == has_permission:
            errors["role"] = "Approval rule must target exactly one role or permission."
            errors["permission"] = "Approval rule must target exactly one role or permission."
        if role is not None and role.app != self.app:
            errors["role"] = "Role must belong to the approval rule app."
        if permission is not None and permission.app != self.app:
            errors["permission"] = "Permission must belong to the approval rule app."

        match self.approver_userids:
            case list() as approver_userids if approver_userids and all(
                isinstance(userid, str) and userid for userid in approver_userids
            ):
                pass
            case _:
                errors["approver_userids"] = "DingTalk approver userids must be a non-empty list."

        if errors:
            raise ValidationError(errors)
