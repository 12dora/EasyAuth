from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, cast, override

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AppScope, AuthorizationGroup, Permission

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

# 授权成员来源: user = 显式授权(审批通过/交接/管理员直接授予); department = 由部门预授权策略物化。
MEMBERSHIP_SOURCE_USER: Final = "user"
MEMBERSHIP_SOURCE_DEPARTMENT: Final = "department"
MEMBERSHIP_SOURCE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (MEMBERSHIP_SOURCE_USER, "user"),
    (MEMBERSHIP_SOURCE_DEPARTMENT, "department"),
)
MEMBERSHIP_SOURCE_VALUES: Final[tuple[str, ...]] = (
    MEMBERSHIP_SOURCE_USER,
    MEMBERSHIP_SOURCE_DEPARTMENT,
)


class AccessGrant(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        user_id: ClassVar[int]
        app_id: ClassVar[int]

    user: models.ForeignKey[UserMirror, UserMirror] = models.ForeignKey(
        UserMirror,
        on_delete=models.PROTECT,
        related_name="access_grants",
    )
    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="access_grants",
    )
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
                condition=Q(status__in=GRANT_STATUS_VALUES),
                name="grants_access_grant_status_supported",
            ),
            models.UniqueConstraint(
                fields=["user", "app"],
                condition=Q(is_current=True),
                name="grants_access_grant_one_current",
            ),
            # snapshot_version 以 (user, app, version) 为事实锚点;
            # 并发 revoke(就地 +1)与新建授权不允许产生两行相同版本号。
            models.UniqueConstraint(
                fields=["user", "app", "version"],
                name="grants_access_grant_version_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["app__app_key", "user__authentik_user_id", "-version"]

    @override
    def __str__(self) -> str:
        return f"{self.user.authentik_user_id}:{self.app.app_key}:v{self.version}"


class DepartmentGrantPolicy(models.Model):
    """部门预授权策略: 挂在钉钉部门上, 对该部门及其全部子部门的在职人员自动生效。"""

    if TYPE_CHECKING:
        id: ClassVar[int]
        app_id: ClassVar[int]

    source_slug: models.CharField[str, str] = models.CharField(max_length=128)
    corp_id: models.CharField[str, str] = models.CharField(max_length=128)
    dept_id: models.CharField[str, str] = models.CharField(max_length=128)
    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.PROTECT,
        related_name="department_grant_policies",
    )
    grant_type: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=GRANT_TYPE_CHOICES,
    )
    expires_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True, db_index=True)
    reason: models.CharField[str, str] = models.CharField(max_length=1000)
    created_by_type: models.CharField[str, str] = models.CharField(max_length=32)
    created_by_id: models.CharField[str, str] = models.CharField(max_length=128)
    updated_by_type: models.CharField[str, str] = models.CharField(max_length=32)
    updated_by_id: models.CharField[str, str] = models.CharField(max_length=128)
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
                name="grants_department_policy_grant_type_supported",
            ),
            models.CheckConstraint(
                condition=(
                    Q(grant_type=GRANT_TYPE_TIMED, expires_at__isnull=False)
                    | Q(grant_type=GRANT_TYPE_PERMANENT, expires_at__isnull=True)
                ),
                name="grants_department_policy_expiry_shape",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["source_slug", "corp_id", "dept_id"],
                name="grants_dept_policy_dept_idx",
            ),
        ]
        ordering: ClassVar[list[str]] = ["app__app_key", "dept_id", "id"]

    @override
    def __str__(self) -> str:
        return f"{self.source_slug}/{self.corp_id}/{self.dept_id}:{self.app.app_key}:{self.id}"


class DepartmentGrantPolicyGroup(models.Model):
    if TYPE_CHECKING:
        policy_id: ClassVar[int]
        authorization_group_id: ClassVar[int]

    policy: models.ForeignKey[DepartmentGrantPolicy, DepartmentGrantPolicy] = models.ForeignKey(
        DepartmentGrantPolicy,
        on_delete=models.CASCADE,
        related_name="policy_groups",
    )
    authorization_group: models.ForeignKey[AuthorizationGroup, AuthorizationGroup] = (
        models.ForeignKey(
            AuthorizationGroup,
            on_delete=models.CASCADE,
            related_name="department_policy_groups",
        )
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["policy", "authorization_group"],
                name="grants_department_policy_group_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["policy_id", "authorization_group__key"]

    @override
    def __str__(self) -> str:
        return f"{self.policy} -> {self.authorization_group}"

    @override
    def clean(self) -> None:
        super().clean()
        if self.authorization_group.app_id != self.policy.app_id:
            raise ValidationError(
                {"authorization_group": "Authorization group must belong to the policy app."},
            )


class DepartmentGrantPolicyPermission(models.Model):
    if TYPE_CHECKING:
        policy_id: ClassVar[int]
        permission_id: ClassVar[int]

    policy: models.ForeignKey[DepartmentGrantPolicy, DepartmentGrantPolicy] = models.ForeignKey(
        DepartmentGrantPolicy,
        on_delete=models.CASCADE,
        related_name="policy_permissions",
    )
    permission: models.ForeignKey[Permission, Permission] = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name="department_policy_permissions",
    )
    scope_key: models.CharField[str, str] = models.CharField(max_length=64, default="GLOBAL")

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["policy", "permission", "scope_key"],
                name="grants_department_policy_permission_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["policy_id", "permission__key", "scope_key"]

    @override
    def __str__(self) -> str:
        return f"{self.policy} -> {self.permission}:{self.scope_key}"

    @override
    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.permission.app_id != self.policy.app_id:
            errors["permission"] = "Permission must belong to the policy app."
        supported_scopes = cast("list[str]", self.permission.supported_scopes)
        if self.scope_key not in supported_scopes:
            errors["scope_key"] = "Scope must be supported by the permission."
        if errors:
            raise ValidationError(errors)


class AccessGrantGroup(models.Model):
    if TYPE_CHECKING:
        grant_id: ClassVar[int]
        authorization_group_id: ClassVar[int]

    grant: models.ForeignKey[AccessGrant, AccessGrant] = models.ForeignKey(
        AccessGrant,
        on_delete=models.CASCADE,
        related_name="grant_groups",
    )
    authorization_group: models.ForeignKey[AuthorizationGroup, AuthorizationGroup] = (
        models.ForeignKey(
            AuthorizationGroup,
            on_delete=models.CASCADE,
            related_name="access_grant_groups",
        )
    )
    expires_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True, db_index=True)
    source: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=MEMBERSHIP_SOURCE_CHOICES,
        default=MEMBERSHIP_SOURCE_USER,
    )
    department_policy: models.ForeignKey[
        DepartmentGrantPolicy | None,
        DepartmentGrantPolicy | None,
    ] = models.ForeignKey(
        DepartmentGrantPolicy,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["grant", "authorization_group", "source"],
                name="grants_access_grant_group_unique",
            ),
            models.CheckConstraint(
                condition=Q(source__in=MEMBERSHIP_SOURCE_VALUES),
                name="grants_access_grant_group_source_supported",
            ),
        ]
        ordering: ClassVar[list[str]] = ["grant_id", "authorization_group__key"]

    @override
    def __str__(self) -> str:
        return f"{self.grant} -> {self.authorization_group}"

    @override
    def clean(self) -> None:
        super().clean()
        if self.authorization_group.app_id != self.grant.app_id:
            raise ValidationError(
                {"authorization_group": "Authorization group must belong to the access grant app."},
            )


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
    scope_key: models.CharField[str, str] = models.CharField(max_length=64, default="GLOBAL")
    source_note: models.TextField[str, str] = models.TextField(blank=True, default="")
    expires_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True, db_index=True)
    source: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=MEMBERSHIP_SOURCE_CHOICES,
        default=MEMBERSHIP_SOURCE_USER,
    )
    department_policy: models.ForeignKey[
        DepartmentGrantPolicy | None,
        DepartmentGrantPolicy | None,
    ] = models.ForeignKey(
        DepartmentGrantPolicy,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="+",
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["grant", "permission", "scope_key", "source"],
                name="grants_access_grant_permission_unique",
            ),
            models.CheckConstraint(
                condition=Q(source__in=MEMBERSHIP_SOURCE_VALUES),
                name="grants_access_grant_permission_source_supported",
            ),
        ]
        ordering: ClassVar[list[str]] = ["grant_id", "permission__key", "scope_key"]

    @override
    def __str__(self) -> str:
        return f"{self.grant} -> {self.permission}"

    @override
    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.permission.app_id != self.grant.app_id:
            errors["permission"] = "Permission must belong to the access grant app."

        scope_exists = AppScope.objects.filter(
            app_id=self.grant.app_id,
            key=self.scope_key,
        ).exists()
        if not scope_exists:
            errors["scope_key"] = "Scope must belong to the access grant app."

        supported_scopes = cast("list[str]", self.permission.supported_scopes)
        if self.scope_key not in supported_scopes:
            errors["scope_key"] = "Scope must be supported by the permission."

        if errors:
            raise ValidationError(errors)
