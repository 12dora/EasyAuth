from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, cast, override

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AppScope, AuthorizationGroup, Permission
from easyauth.grants.models import AccessGrant

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
REQUEST_STATUS_GRANT_CONFLICT: Final = "grant_conflict"
REQUEST_STATUS_GRANT_EXPIRED: Final = "grant_expired"
REQUEST_STATUS_WITHDRAWN: Final = "withdrawn"
REQUEST_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (REQUEST_STATUS_SUBMITTED, "submitted"),
    (REQUEST_STATUS_APPROVED, "approved"),
    (REQUEST_STATUS_REJECTED, "rejected"),
    (REQUEST_STATUS_GRANT_APPLIED, "grant_applied"),
    (REQUEST_STATUS_GRANT_FAILED, "grant_failed"),
    (REQUEST_STATUS_GRANT_CONFLICT, "grant_conflict"),
    (REQUEST_STATUS_GRANT_EXPIRED, "grant_expired"),
    (REQUEST_STATUS_WITHDRAWN, "withdrawn"),
)
REQUEST_STATUS_VALUES: Final[tuple[str, ...]] = (
    REQUEST_STATUS_SUBMITTED,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_REJECTED,
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_STATUS_GRANT_CONFLICT,
    REQUEST_STATUS_GRANT_EXPIRED,
    REQUEST_STATUS_WITHDRAWN,
)

GRANT_TYPE_TIMED: Final = "timed"
GRANT_TYPE_PERMANENT: Final = "permanent"
GRANT_TYPE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (GRANT_TYPE_TIMED, "timed"),
    (GRANT_TYPE_PERMANENT, "permanent"),
)
GRANT_TYPE_VALUES: Final[tuple[str, ...]] = (GRANT_TYPE_TIMED, GRANT_TYPE_PERMANENT)

# 审批决定的操作者类别: 站内审批人本人, 或控制台管理员代审。
DECISION_ACTOR_USER: Final = "user"
DECISION_ACTOR_CONSOLE_ADMIN: Final = "console_admin"
DECISION_ACTOR_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (DECISION_ACTOR_USER, "user"),
    (DECISION_ACTOR_CONSOLE_ADMIN, "console_admin"),
)
PAYLOAD_DIGEST_LENGTH: Final = 64


class AccessRequest(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        user_id: ClassVar[int]
        app_id: ClassVar[int]
        base_grant_id: ClassVar[int | None]
        loaded_approver_assignments: ClassVar[list[AccessRequestApprover]]

    user: models.ForeignKey[UserMirror, UserMirror] = models.ForeignKey(
        UserMirror,
        on_delete=models.PROTECT,
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
    idempotency_key: models.CharField[str, str] = models.CharField(max_length=128)
    payload_digest: models.CharField[str, str] = models.CharField(max_length=64, editable=False)
    base_grant: models.ForeignKey[AccessGrant | None, AccessGrant | None] = models.ForeignKey(
        AccessGrant,
        on_delete=models.PROTECT,
        related_name="access_requests",
        blank=True,
        null=True,
    )
    base_grant_revision: models.PositiveIntegerField[int | None, int | None] = (
        models.PositiveIntegerField(blank=True, null=True)
    )
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
    # 站内审批闭环的决定记录: 谁(decided_by)以什么身份(decision_actor_type)
    # 在什么时候(decided_at)做了决定, 意见(decision_comment)驳回时必填。
    decided_by: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    decision_actor_type: models.CharField[str, str] = models.CharField(
        max_length=32,
        choices=DECISION_ACTOR_CHOICES,
        blank=True,
    )
    decision_comment: models.TextField[str, str] = models.TextField(blank=True)
    decided_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    # 01 §4.5.1: 审批人无解时 status 保持 submitted, 路由状态进超管池。
    approval_routing_state: models.CharField[str, str] = models.CharField(
        max_length=16,
        default="normal",
    )
    routing_reason: models.CharField[str, str] = models.CharField(max_length=64, blank=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(request_type__in=REQUEST_TYPE_VALUES),
                name="access_requests_request_type_supported",
            ),
            models.CheckConstraint(
                condition=Q(approval_routing_state__in=("normal", "superuser_pool")),
                name="access_requests_approval_routing_state_supported",
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
            models.CheckConstraint(
                condition=(
                    Q(
                        request_type=REQUEST_TYPE_GRANT,
                        base_grant__isnull=True,
                        base_grant_revision__isnull=True,
                    )
                    | Q(
                        request_type__in=(
                            REQUEST_TYPE_CHANGE,
                            REQUEST_TYPE_REVOKE,
                            REQUEST_TYPE_RENEW,
                        ),
                        base_grant__isnull=False,
                        base_grant_revision__isnull=False,
                    )
                ),
                name="access_requests_base_grant_shape",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status=REQUEST_STATUS_SUBMITTED,
                        approved_at__isnull=True,
                        applied_at__isnull=True,
                        decided_by="",
                        decision_actor_type="",
                        decision_comment="",
                        decided_at__isnull=True,
                    )
                    | Q(
                        status=REQUEST_STATUS_APPROVED,
                        approved_at__isnull=False,
                        applied_at__isnull=True,
                        decided_by__gt="",
                        decision_actor_type__in=(
                            DECISION_ACTOR_USER,
                            DECISION_ACTOR_CONSOLE_ADMIN,
                        ),
                        decided_at__isnull=False,
                    )
                    | Q(
                        status=REQUEST_STATUS_REJECTED,
                        approved_at__isnull=True,
                        applied_at__isnull=True,
                        decided_by__gt="",
                        decision_actor_type__in=(
                            DECISION_ACTOR_USER,
                            DECISION_ACTOR_CONSOLE_ADMIN,
                        ),
                        decision_comment__gt="",
                        decided_at__isnull=False,
                    )
                    | Q(
                        status=REQUEST_STATUS_GRANT_APPLIED,
                        approved_at__isnull=False,
                        applied_at__isnull=False,
                        decided_by__gt="",
                        decision_actor_type__in=(
                            DECISION_ACTOR_USER,
                            DECISION_ACTOR_CONSOLE_ADMIN,
                        ),
                        decided_at__isnull=False,
                    )
                    | Q(
                        status__in=(
                            REQUEST_STATUS_GRANT_FAILED,
                            REQUEST_STATUS_GRANT_CONFLICT,
                            REQUEST_STATUS_GRANT_EXPIRED,
                        ),
                        approved_at__isnull=False,
                        applied_at__isnull=True,
                        decided_by__gt="",
                        decision_actor_type__in=(
                            DECISION_ACTOR_USER,
                            DECISION_ACTOR_CONSOLE_ADMIN,
                        ),
                        decided_at__isnull=False,
                    )
                    | Q(
                        status=REQUEST_STATUS_WITHDRAWN,
                        approved_at__isnull=True,
                        applied_at__isnull=True,
                        decided_by="",
                        decision_actor_type="",
                        decision_comment="",
                        decided_at__isnull=True,
                    )
                ),
                name="access_requests_status_field_shape",
            ),
            models.UniqueConstraint(
                fields=["user", "idempotency_key"],
                name="access_requests_user_idempotency_key_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["-submitted_at", "id"]

    @override
    def __str__(self) -> str:
        return f"{self.user.authentik_user_id}:{self.app.app_key}:{self.request_type}"

    @override
    def clean(self) -> None:  # noqa: C901, PLR0912
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
        if self.request_type == REQUEST_TYPE_GRANT:
            if self.base_grant_id is not None or self.base_grant_revision is not None:
                errors["base_grant"] = "Grant requests must not include a base grant."
        elif self.base_grant_id is None or self.base_grant_revision is None:
            errors["base_grant"] = "Lifecycle access requests must include a base grant revision."
        if (
            self.base_grant_id is not None
            and self.base_grant is not None
            and (self.base_grant.user_id != self.user_id or self.base_grant.app_id != self.app_id)
        ):
            errors["base_grant"] = "Base grant must belong to the request user and app."
        if self.status == REQUEST_STATUS_APPROVED and self.approved_at is None:
            errors["approved_at"] = "Approved access requests must include approved_at."
        if self.status in {
            REQUEST_STATUS_APPROVED,
            REQUEST_STATUS_REJECTED,
            REQUEST_STATUS_GRANT_APPLIED,
            REQUEST_STATUS_GRANT_FAILED,
            REQUEST_STATUS_GRANT_CONFLICT,
            REQUEST_STATUS_GRANT_EXPIRED,
        }:
            if self.decided_at is None:
                errors["decided_at"] = "Decided access requests must include decided_at."
            if not self.decided_by:
                errors["decided_by"] = "Decided access requests must include decided_by."
            if self.decision_actor_type not in {DECISION_ACTOR_USER, DECISION_ACTOR_CONSOLE_ADMIN}:
                errors["decision_actor_type"] = (
                    "Decided access requests must include decision_actor_type."
                )
        elif self.decided_at is not None or self.decided_by or self.decision_actor_type:
            errors["decided_at"] = "Undecided access requests must not include decision fields."
        if self.status == REQUEST_STATUS_REJECTED and not self.decision_comment:
            errors["decision_comment"] = "Rejected access requests must include decision_comment."
        if not self.idempotency_key or self.idempotency_key != self.idempotency_key.strip():
            errors["idempotency_key"] = "A non-empty opaque idempotency key is required."
        if len(self.payload_digest) != PAYLOAD_DIGEST_LENGTH or any(
            character not in "0123456789abcdef" for character in self.payload_digest
        ):
            errors["payload_digest"] = "Payload digest must be a lowercase SHA-256 digest."
        if errors:
            raise ValidationError(errors)


class AccessRequestApprover(models.Model):
    if TYPE_CHECKING:
        access_request_id: ClassVar[int]
        approver_id: ClassVar[int]

    access_request: models.ForeignKey[AccessRequest, AccessRequest] = models.ForeignKey(
        AccessRequest,
        on_delete=models.CASCADE,
        related_name="approver_assignments",
    )
    approver: models.ForeignKey[UserMirror, UserMirror] = models.ForeignKey(
        UserMirror,
        on_delete=models.PROTECT,
        related_name="approval_assignments",
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["access_request", "approver"],
                name="access_requests_request_approver_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["access_request_id", "approver__authentik_user_id"]

    @override
    def __str__(self) -> str:
        return f"{self.access_request} -> {self.approver.authentik_user_id}"


class AccessRequestGroup(models.Model):
    if TYPE_CHECKING:
        access_request_id: ClassVar[int]
        authorization_group_id: ClassVar[int]

    access_request: models.ForeignKey[AccessRequest, AccessRequest] = models.ForeignKey(
        AccessRequest,
        on_delete=models.CASCADE,
        related_name="target_groups",
    )
    authorization_group: models.ForeignKey[AuthorizationGroup, AuthorizationGroup] = (
        models.ForeignKey(
            AuthorizationGroup,
            on_delete=models.CASCADE,
            related_name="access_request_groups",
        )
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


class AccessRequestGroupGrantSnapshot(models.Model):
    if TYPE_CHECKING:
        access_request_id: ClassVar[int]

    access_request: models.ForeignKey[AccessRequest, AccessRequest] = models.ForeignKey(
        AccessRequest,
        on_delete=models.CASCADE,
        related_name="group_grant_snapshots",
    )
    authorization_group_id_snapshot: models.PositiveBigIntegerField[int, int] = (
        models.PositiveBigIntegerField()
    )
    authorization_group_key: models.CharField[str, str] = models.CharField(max_length=128)
    authorization_group_kind: models.CharField[str, str] = models.CharField(max_length=32)
    authorization_group_name: models.CharField[str, str] = models.CharField(max_length=255)
    permission_key: models.CharField[str, str] = models.CharField(max_length=128)
    permission_name: models.CharField[str, str] = models.CharField(max_length=255)
    scope_key: models.CharField[str, str] = models.CharField(max_length=128)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=[
                    "access_request",
                    "authorization_group_id_snapshot",
                    "permission_key",
                    "scope_key",
                ],
                name="access_requests_group_grant_snapshot_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = [
            "access_request_id",
            "authorization_group_id_snapshot",
            "permission_key",
            "scope_key",
        ]

    @override
    def __str__(self) -> str:
        return (
            f"{self.access_request} -> "
            f"{self.authorization_group_key}:{self.permission_key}:{self.scope_key}"
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

        supported_scopes = cast("list[str]", self.permission.supported_scopes)
        if self.scope_key not in supported_scopes:
            errors["scope_key"] = "Scope key must be supported by the permission."

        scope_exists = AppScope.objects.filter(
            app_id=self.access_request.app_id,
            key=self.scope_key,
        ).exists()
        if not scope_exists:
            errors["scope_key"] = "Scope key must reference an app scope."

        if errors:
            raise ValidationError(errors)
