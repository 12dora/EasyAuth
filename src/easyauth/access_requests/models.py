from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, override

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, Permission, Role

if TYPE_CHECKING:
    from datetime import date, datetime

REQUEST_TYPE_GRANT: Final = "grant"
REQUEST_TYPE_CHANGE: Final = "change"
REQUEST_TYPE_REVOKE: Final = "revoke"
REQUEST_TYPE_RENEW: Final = "renew"
REQUEST_TYPE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (REQUEST_TYPE_GRANT, "grant"),
    (REQUEST_TYPE_CHANGE, "change"),
    (REQUEST_TYPE_REVOKE, "revoke"),
    (REQUEST_TYPE_RENEW, "renew"),
)
REQUEST_TYPE_VALUES: Final[tuple[str, ...]] = (
    REQUEST_TYPE_GRANT,
    REQUEST_TYPE_CHANGE,
    REQUEST_TYPE_REVOKE,
    REQUEST_TYPE_RENEW,
)

REQUEST_STATUS_SUBMITTED: Final = "submitted"
REQUEST_STATUS_APPROVED: Final = "approved"
REQUEST_STATUS_REJECTED: Final = "rejected"
REQUEST_STATUS_GRANT_APPLIED: Final = "grant_applied"
REQUEST_STATUS_GRANT_FAILED: Final = "grant_failed"
REQUEST_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (REQUEST_STATUS_SUBMITTED, "submitted"),
    (REQUEST_STATUS_APPROVED, "approved"),
    (REQUEST_STATUS_REJECTED, "rejected"),
    (REQUEST_STATUS_GRANT_APPLIED, "grant_applied"),
    (REQUEST_STATUS_GRANT_FAILED, "grant_failed"),
)
REQUEST_STATUS_VALUES: Final[tuple[str, ...]] = (
    REQUEST_STATUS_SUBMITTED,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_REJECTED,
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_GRANT_FAILED,
)

GRANT_TYPE_TIMED: Final = "timed"
GRANT_TYPE_PERMANENT: Final = "permanent"
GRANT_TYPE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (GRANT_TYPE_TIMED, "timed"),
    (GRANT_TYPE_PERMANENT, "permanent"),
)
GRANT_TYPE_VALUES: Final[tuple[str, ...]] = (GRANT_TYPE_TIMED, GRANT_TYPE_PERMANENT)


class AccessRequest(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]

    user: models.ForeignKey[UserMirror, UserMirror] = models.ForeignKey(
        UserMirror,
        on_delete=models.CASCADE,
        related_name="access_requests",
    )
    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="access_requests",
    )
    request_type: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=REQUEST_TYPE_CHOICES,
        default=REQUEST_TYPE_GRANT,
    )
    status: models.CharField[str, str] = models.CharField(
        max_length=32,
        choices=REQUEST_STATUS_CHOICES,
        default=REQUEST_STATUS_SUBMITTED,
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
    reason: models.TextField[str, str] = models.TextField(blank=True)
    submitted_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    approved_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    applied_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    dingtalk_process_instance_id: models.CharField[str | None, str | None] = models.CharField(
        max_length=128,
        unique=True,
        blank=True,
        null=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(request_type__in=REQUEST_TYPE_VALUES),
                name="access_requests_request_type_supported",
            ),
            models.CheckConstraint(
                condition=Q(status__in=REQUEST_STATUS_VALUES),
                name="access_requests_status_supported",
            ),
            models.CheckConstraint(
                condition=(
                    Q(grant_type=GRANT_TYPE_TIMED, grant_expires_at__isnull=False)
                    | Q(grant_type=GRANT_TYPE_PERMANENT, grant_expires_at__isnull=True)
                ),
                name="access_requests_grant_expiration_shape",
            ),
        ]
        ordering: ClassVar[list[str]] = ["-submitted_at", "id"]

    @override
    def __str__(self) -> str:
        return f"{self.user.authentik_user_id}:{self.app.app_key}:{self.request_type}"

    @override
    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.grant_type == GRANT_TYPE_TIMED and self.grant_expires_at is None:
            errors["grant_expires_at"] = "Timed access requests must include an expiration."
        if self.grant_type == GRANT_TYPE_PERMANENT and self.grant_expires_at is not None:
            errors["grant_expires_at"] = "Permanent access requests must not include an expiration."
        if self.status == REQUEST_STATUS_GRANT_APPLIED and self.applied_at is None:
            errors["applied_at"] = "Grant-applied access requests must include applied_at."
        if self.status != REQUEST_STATUS_GRANT_APPLIED and self.applied_at is not None:
            errors["applied_at"] = "Only grant-applied access requests may include applied_at."
        if errors:
            raise ValidationError(errors)


class AccessRequestRole(models.Model):
    if TYPE_CHECKING:
        access_request_id: ClassVar[int]

    access_request: models.ForeignKey[AccessRequest, AccessRequest] = models.ForeignKey(
        AccessRequest,
        on_delete=models.CASCADE,
        related_name="target_roles",
    )
    role: models.ForeignKey[Role, Role] = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="access_request_roles",
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["access_request", "role"],
                name="access_requests_request_role_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["access_request_id", "role__key"]

    @override
    def __str__(self) -> str:
        return f"{self.access_request} -> {self.role}"

    @override
    def clean(self) -> None:
        super().clean()
        if self.role.app != self.access_request.app:
            raise ValidationError({"role": "Role must belong to the access request app."})


class AccessRequestGroup(models.Model):
    if TYPE_CHECKING:
        access_request_id: ClassVar[int]
        authorization_group_id: ClassVar[int]

    access_request: models.ForeignKey[AccessRequest, AccessRequest] = models.ForeignKey(
        AccessRequest,
        on_delete=models.CASCADE,
        related_name="target_groups",
    )
    authorization_group = models.ForeignKey(
        "applications.AuthorizationGroup",
        on_delete=models.CASCADE,
        related_name="access_request_groups",
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["access_request", "authorization_group"],
                name="access_requests_request_group_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["access_request_id", "authorization_group__key"]

    @override
    def __str__(self) -> str:
        return f"{self.access_request} -> {self.authorization_group}"

    @override
    def clean(self) -> None:
        super().clean()
        if self.authorization_group.app_id != self.access_request.app_id:
            raise ValidationError(
                {
                    "authorization_group": (
                        "Authorization group must belong to the access request app."
                    ),
                },
            )


class AccessRequestPermission(models.Model):
    access_request: models.ForeignKey[AccessRequest, AccessRequest] = models.ForeignKey(
        AccessRequest,
        on_delete=models.CASCADE,
        related_name="target_permissions",
    )
    permission: models.ForeignKey[Permission, Permission] = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name="access_request_permissions",
    )
    scope_key: models.CharField[str, str] = models.CharField(max_length=128, default="GLOBAL")
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["access_request", "permission", "scope_key"],
                name="access_requests_request_permission_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["access_request_id", "permission__key", "scope_key"]

    @override
    def __str__(self) -> str:
        return f"{self.access_request} -> {self.permission}:{self.scope_key}"

    @override
    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.permission.app_id != self.access_request.app_id:
            errors["permission"] = "Permission must belong to the access request app."

        supported_scopes = self.permission.supported_scopes
        if self.scope_key not in supported_scopes:
            errors["scope_key"] = "Scope key must be supported by the permission."

        AppScope = apps.get_model("applications", "AppScope")
        scope_exists = AppScope.objects.filter(
            app_id=self.access_request.app_id,
            key=self.scope_key,
        ).exists()
        if not scope_exists:
            errors["scope_key"] = "Scope key must reference an app scope."

        if errors:
            raise ValidationError(errors)
