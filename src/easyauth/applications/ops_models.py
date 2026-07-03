from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, Protocol, override

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .health_models import (
    DEPENDENCY_AUTHENTIK,
    DEPENDENCY_AUTHENTIK_DIRECTORY,
    DEPENDENCY_CELERY,
    DEPENDENCY_DINGTALK,
    DEPENDENCY_HEALTH_STATUS_HEALTHY,
    DEPENDENCY_HEALTH_STATUS_UNHEALTHY,
    DEPENDENCY_HEALTH_STATUS_UNKNOWN,
    DEPENDENCY_HEALTH_STATUS_WARNING,
    DependencyHealthSnapshot,
)
from .permission_group_rules import (
    PERMISSION_GROUP_MAX_DEPTH,
    permission_group_clean_errors,
)
from .role_access_policy_rules import role_access_policy_max_duration_clean_errors

__all__ = (
    "APP_MEMBERSHIP_ROLE_CHOICES",
    "APP_MEMBERSHIP_ROLE_DEVELOPER",
    "APP_MEMBERSHIP_ROLE_OWNER",
    "APP_MEMBERSHIP_ROLE_VALUES",
    "DEPENDENCY_AUTHENTIK",
    "DEPENDENCY_AUTHENTIK_DIRECTORY",
    "DEPENDENCY_CELERY",
    "DEPENDENCY_DINGTALK",
    "DEPENDENCY_HEALTH_STATUS_HEALTHY",
    "DEPENDENCY_HEALTH_STATUS_UNHEALTHY",
    "DEPENDENCY_HEALTH_STATUS_UNKNOWN",
    "DEPENDENCY_HEALTH_STATUS_WARNING",
    "PERMISSION_GROUP_MAX_DEPTH",
    "TEMPLATE_SOURCE_CHOICES",
    "TEMPLATE_SOURCE_MANUAL",
    "TEMPLATE_SOURCE_PASTE",
    "TEMPLATE_SOURCE_UPLOAD",
    "TEMPLATE_STATUS_CHOICES",
    "TEMPLATE_STATUS_IMPORTED",
    "TEMPLATE_STATUS_REJECTED",
    "AppMembership",
    "AuthorizationGroupAccessPolicy",
    "DependencyHealthSnapshot",
    "PermissionGroup",
    "PermissionTemplateVersion",
    "RoleAccessPolicy",
)

if TYPE_CHECKING:
    from datetime import date, datetime

APP_MEMBERSHIP_ROLE_OWNER: Final = "owner"
APP_MEMBERSHIP_ROLE_DEVELOPER: Final = "developer"
APP_MEMBERSHIP_ROLE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (APP_MEMBERSHIP_ROLE_OWNER, "owner"),
    (APP_MEMBERSHIP_ROLE_DEVELOPER, "developer"),
)
APP_MEMBERSHIP_ROLE_VALUES: Final[tuple[str, ...]] = (
    APP_MEMBERSHIP_ROLE_OWNER,
    APP_MEMBERSHIP_ROLE_DEVELOPER,
)
TEMPLATE_SOURCE_UPLOAD: Final = "upload"
TEMPLATE_SOURCE_PASTE: Final = "paste"
TEMPLATE_SOURCE_MANUAL: Final = "manual"
TEMPLATE_SOURCE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (TEMPLATE_SOURCE_UPLOAD, "upload"),
    (TEMPLATE_SOURCE_PASTE, "paste"),
    (TEMPLATE_SOURCE_MANUAL, "manual"),
)
TEMPLATE_STATUS_IMPORTED: Final = "imported"
TEMPLATE_STATUS_REJECTED: Final = "rejected"
TEMPLATE_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (TEMPLATE_STATUS_IMPORTED, "imported"),
    (TEMPLATE_STATUS_REJECTED, "rejected"),
)

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


class _BoundApp(Protocol):
    id: int
    app_key: str


class _BoundRole(Protocol):
    id: int
    app_id: int
    key: str


class AppMembership(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]

    app: models.ForeignKey[_BoundApp, _BoundApp] = models.ForeignKey(
        "applications.App",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user_id: models.CharField[str, str] = models.CharField(max_length=128)
    role: models.CharField[str, str] = models.CharField(
        max_length=32,
        choices=APP_MEMBERSHIP_ROLE_CHOICES,
    )
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
                fields=["app", "user_id", "role"],
                name="applications_app_membership_unique",
            ),
            models.CheckConstraint(
                condition=Q(role__in=APP_MEMBERSHIP_ROLE_VALUES),
                name="applications_app_membership_role_supported",
            ),
        ]
        ordering: ClassVar[list[str]] = ["app__app_key", "user_id", "role"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.user_id}:{self.role}"


class PermissionGroup(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        app_id: ClassVar[int]

    app: models.ForeignKey[_BoundApp, _BoundApp] = models.ForeignKey(
        "applications.App",
        on_delete=models.CASCADE,
        related_name="permission_groups",
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
    parent: models.ForeignKey[PermissionGroup | None, PermissionGroup | None] = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="children",
        blank=True,
        null=True,
    )
    display_order: models.IntegerField[int, int] = models.IntegerField(default=0)
    depth: models.PositiveSmallIntegerField[int, int] = models.PositiveSmallIntegerField(default=1)
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
                name="applications_permission_group_app_key_unique",
            ),
            models.CheckConstraint(
                condition=Q(depth__gte=1, depth__lte=PERMISSION_GROUP_MAX_DEPTH),
                name="applications_permission_group_depth_supported",
            ),
        ]
        ordering: ClassVar[list[str]] = ["app__app_key", "depth", "display_order", "key"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.key}"

    @override
    def clean(self) -> None:
        super().clean()
        errors = permission_group_clean_errors(self)
        if errors:
            raise ValidationError(errors)


class PermissionTemplateVersion(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]

    app: models.ForeignKey[_BoundApp, _BoundApp] = models.ForeignKey(
        "applications.App",
        on_delete=models.CASCADE,
        related_name="permission_template_versions",
    )
    version: models.PositiveIntegerField[int, int] = models.PositiveIntegerField()
    source: models.CharField[str, str] = models.CharField(
        max_length=32,
        choices=TEMPLATE_SOURCE_CHOICES,
    )
    content_hash: models.CharField[str, str] = models.CharField(max_length=64)
    raw_template: models.TextField[str, str] = models.TextField(blank=True)
    import_summary: models.JSONField[JsonValue, JsonValue] = models.JSONField(default=dict)
    imported_by: models.CharField[str, str] = models.CharField(max_length=128)
    imported_at: models.DateTimeField[datetime, datetime] = models.DateTimeField(
        default=timezone.now,
    )
    status: models.CharField[str, str] = models.CharField(
        max_length=32,
        choices=TEMPLATE_STATUS_CHOICES,
        default=TEMPLATE_STATUS_IMPORTED,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["app", "version"],
                name="applications_permission_template_version_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["app__app_key", "-version"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:v{self.version}"


class RoleAccessPolicy(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        role_id: ClassVar[int]

    role: models.ForeignKey[_BoundRole, _BoundRole] = models.ForeignKey(
        "applications.Role",
        on_delete=models.CASCADE,
        related_name="access_policies",
    )
    is_high_risk: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    max_grant_duration_days: models.PositiveIntegerField[int | None, int | None] = (
        models.PositiveIntegerField(blank=True, null=True)
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["role"], name="applications_role_access_policy_unique"),
            models.CheckConstraint(
                condition=Q(max_grant_duration_days__isnull=True)
                | Q(max_grant_duration_days__gte=1),
                name="applications_role_access_policy_max_duration_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_high_risk=True, max_grant_duration_days__isnull=False)
                    | Q(is_high_risk=False, max_grant_duration_days__isnull=True)
                ),
                name="applications_role_access_policy_high_risk_shape",
            ),
        ]
        ordering: ClassVar[list[str]] = ["role__app__app_key", "role__key"]

    @override
    def __str__(self) -> str:
        return f"{self.role}:access-policy"

    @override
    def clean(self) -> None:
        super().clean()
        errors = role_access_policy_max_duration_clean_errors(
            is_high_risk=self.is_high_risk,
            max_grant_duration_days=self.max_grant_duration_days,
        )
        if errors:
            raise ValidationError(errors)


class AuthorizationGroupAccessPolicy(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        authorization_group_id: ClassVar[int]

    authorization_group = models.ForeignKey(
        "applications.AuthorizationGroup",
        on_delete=models.CASCADE,
        related_name="access_policies",
    )
    is_high_risk: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    max_grant_duration_days: models.PositiveIntegerField[int | None, int | None] = (
        models.PositiveIntegerField(blank=True, null=True)
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["authorization_group"],
                name="applications_authorization_group_access_policy_unique",
            ),
            models.CheckConstraint(
                condition=Q(max_grant_duration_days__isnull=True)
                | Q(max_grant_duration_days__gte=1),
                name="applications_authorization_group_access_policy_max_duration_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_high_risk=True, max_grant_duration_days__isnull=False)
                    | Q(is_high_risk=False, max_grant_duration_days__isnull=True)
                ),
                name="applications_authorization_group_access_policy_high_risk_shape",
            ),
        ]
        ordering: ClassVar[list[str]] = [
            "authorization_group__app__app_key",
            "authorization_group__key",
        ]

    @override
    def __str__(self) -> str:
        return f"{self.authorization_group}:access-policy"

    @override
    def clean(self) -> None:
        super().clean()
        errors = role_access_policy_max_duration_clean_errors(
            is_high_risk=self.is_high_risk,
            max_grant_duration_days=self.max_grant_duration_days,
        )
        if errors:
            raise ValidationError(errors)
