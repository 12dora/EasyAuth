"""定义应用 scope, 权限, 授权组及授权组 grant 模型。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, cast, override

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .app import App
from .constants import (
    APP_SCOPE_KEY_PATTERN,
    AUTHORIZATION_GROUP_KINDS,
    PERMISSION_RISK_LEVELS,
    JsonValue,
)

if TYPE_CHECKING:
    from datetime import date, datetime

    from easyauth.applications.ops_models import PermissionGroup


def _is_scope_key_list(value: object) -> bool:
    if not isinstance(value, list):
        return False
    items = cast("list[object]", value)
    scopes = [
        item for item in items if isinstance(item, str) and APP_SCOPE_KEY_PATTERN.fullmatch(item)
    ]
    return len(scopes) == len(items) and len(set(scopes)) == len(scopes)


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
    name_en: models.CharField[str, str] = models.CharField(
        max_length=128,
        blank=True,
        default="",
    )
    description: models.TextField[str, str] = models.TextField(blank=True)
    description_en: models.TextField[str, str] = models.TextField(blank=True, default="")
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
                        "App scope key must contain only uppercase letters, digits, or underscores."
                    ),
                },
            )


class Permission(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        app_id: ClassVar[int]
        group_id: ClassVar[int | None]

    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="permissions",
    )
    group: models.ForeignKey[PermissionGroup | None, PermissionGroup | None] = models.ForeignKey(
        "applications.PermissionGroup",
        on_delete=models.SET_NULL,
        related_name="permissions",
        blank=True,
        null=True,
    )
    key: models.CharField[str, str] = models.CharField(max_length=128)
    name: models.CharField[str, str] = models.CharField(max_length=128)
    name_en: models.CharField[str, str] = models.CharField(
        max_length=128,
        blank=True,
        default="",
    )
    description: models.TextField[str, str] = models.TextField(blank=True)
    description_en: models.TextField[str, str] = models.TextField(blank=True, default="")
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
        # supported_scopes 必须是 scope key 列表; 存成字符串或字典会让
        # `scope_key in supported_scopes` 退化成子串/字典键语义("GLO" in "GLOBAL")。
        if not _is_scope_key_list(self.supported_scopes):
            errors["supported_scopes"] = "Supported scopes must be a list of unique scope keys."
        elif self.is_active and not self.supported_scopes:
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
    name_en: models.CharField[str, str] = models.CharField(
        max_length=128,
        blank=True,
        default="",
    )
    description: models.TextField[str, str] = models.TextField(blank=True)
    description_en: models.TextField[str, str] = models.TextField(blank=True, default="")
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
        scope_is_active = (
            AppScope.objects.filter(app_id=app_id, key=self.scope_key)
            .values_list("is_active", flat=True)
            .first()
        )
        if scope_is_active is None:
            errors["scope_key"] = "Scope key must reference an app scope."
        elif self.is_active and not scope_is_active:
            errors["scope_key"] = "Active grant must reference an active app scope."
        elif self.is_active and not _scope_key_is_supported(
            self.permission.supported_scopes,
            self.scope_key,
        ):
            errors["scope_key"] = "Scope key must be supported by the permission."
        if errors:
            raise ValidationError(errors)


def _scope_key_is_supported(value: JsonValue, scope_key: str) -> bool:
    if not _is_scope_key_list(value):
        return False
    return scope_key in cast("list[str]", value)
