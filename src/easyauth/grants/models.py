from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, override

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, Permission, Role

if TYPE_CHECKING:
    from datetime import date, datetime

GRANT_TYPE_TIMED: Final = "timed"
GRANT_TYPE_PERMANENT: Final = "permanent"
GRANT_TYPE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (GRANT_TYPE_TIMED, "timed"),
    (GRANT_TYPE_PERMANENT, "permanent"),
)
GRANT_TYPE_VALUES: Final[tuple[str, ...]] = (GRANT_TYPE_TIMED, GRANT_TYPE_PERMANENT)

GRANT_STATUS_ACTIVE: Final = "active"
GRANT_STATUS_REVOKED: Final = "revoked"
GRANT_STATUS_EXPIRED: Final = "expired"
GRANT_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (GRANT_STATUS_ACTIVE, "active"),
    (GRANT_STATUS_REVOKED, "revoked"),
    (GRANT_STATUS_EXPIRED, "expired"),
)
GRANT_STATUS_VALUES: Final[tuple[str, ...]] = (
    GRANT_STATUS_ACTIVE,
    GRANT_STATUS_REVOKED,
    GRANT_STATUS_EXPIRED,
)


class AccessGrant(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]

    user: models.ForeignKey[UserMirror, UserMirror] = models.ForeignKey(
        UserMirror,
        on_delete=models.CASCADE,
        related_name="access_grants",
    )
    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="access_grants",
    )
    grant_type: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=GRANT_TYPE_CHOICES,
        default=GRANT_TYPE_PERMANENT,
    )
    grant_expires_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    status: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=GRANT_STATUS_CHOICES,
        default=GRANT_STATUS_ACTIVE,
    )
    is_current: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    version: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=1)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(grant_type__in=GRANT_TYPE_VALUES),
                name="grants_access_grant_type_supported",
            ),
            models.CheckConstraint(
                condition=Q(status__in=GRANT_STATUS_VALUES),
                name="grants_access_grant_status_supported",
            ),
            models.CheckConstraint(
                condition=(
                    Q(grant_type=GRANT_TYPE_TIMED, grant_expires_at__isnull=False)
                    | Q(grant_type=GRANT_TYPE_PERMANENT, grant_expires_at__isnull=True)
                ),
                name="grants_access_grant_expiration_shape",
            ),
            models.UniqueConstraint(
                fields=["user", "app"],
                condition=Q(is_current=True),
                name="grants_access_grant_one_current",
            ),
        ]
        ordering: ClassVar[list[str]] = ["app__app_key", "user__authentik_user_id", "-version"]

    @override
    def __str__(self) -> str:
        return f"{self.user.authentik_user_id}:{self.app.app_key}:v{self.version}"

    @override
    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.grant_type == GRANT_TYPE_TIMED and self.grant_expires_at is None:
            errors["grant_expires_at"] = "Timed grants must include an expiration."
        if self.grant_type == GRANT_TYPE_PERMANENT and self.grant_expires_at is not None:
            errors["grant_expires_at"] = "Permanent grants must not include an expiration."
        if errors:
            raise ValidationError(errors)


class AccessGrantRole(models.Model):
    if TYPE_CHECKING:
        grant_id: ClassVar[int]
        role_id: ClassVar[int]

    grant: models.ForeignKey[AccessGrant, AccessGrant] = models.ForeignKey(
        AccessGrant,
        on_delete=models.CASCADE,
        related_name="grant_roles",
    )
    role: models.ForeignKey[Role, Role] = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="access_grant_roles",
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["grant", "role"],
                name="grants_access_grant_role_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["grant_id", "role__key"]

    @override
    def __str__(self) -> str:
        return f"{self.grant} -> {self.role}"

    @override
    def clean(self) -> None:
        super().clean()
        if self.role.app != self.grant.app:
            raise ValidationError({"role": "Role must belong to the access grant app."})


class AccessGrantPermission(models.Model):
    if TYPE_CHECKING:
        grant_id: ClassVar[int]
        permission_id: ClassVar[int]

    grant: models.ForeignKey[AccessGrant, AccessGrant] = models.ForeignKey(
        AccessGrant,
        on_delete=models.CASCADE,
        related_name="grant_permissions",
    )
    permission: models.ForeignKey[Permission, Permission] = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name="access_grant_permissions",
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["grant", "permission"],
                name="grants_access_grant_permission_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["grant_id", "permission__key"]

    @override
    def __str__(self) -> str:
        return f"{self.grant} -> {self.permission}"

    @override
    def clean(self) -> None:
        super().clean()
        if self.permission.app != self.grant.app:
            raise ValidationError(
                {"permission": "Permission must belong to the access grant app."},
            )
