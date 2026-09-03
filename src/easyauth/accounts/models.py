from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, override

from django.contrib.auth import hashers
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

from easyauth.config.crypto import EncryptedCharField

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date, datetime

    from django.db.models.base import ModelBase

    from easyauth.applications.ops_models import JsonValue

USER_STATUS_ACTIVE: Final = "active"
USER_STATUS_DISABLED: Final = "disabled"
USER_STATUS_DEPARTED: Final = "departed"
USER_MIRROR_DELETE_ERROR: Final = "UserMirror cannot be physically deleted."
USER_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (USER_STATUS_ACTIVE, "active"),
    (USER_STATUS_DISABLED, "disabled"),
    (USER_STATUS_DEPARTED, "departed"),
)


class UserMirrorQuerySet(models.QuerySet["UserMirror"]):
    @override
    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError(USER_MIRROR_DELETE_ERROR)


class UserMirrorManager(models.Manager["UserMirror"]):
    @override
    def get_queryset(self) -> UserMirrorQuerySet:
        return UserMirrorQuerySet(self.model, using=self._db)


class UserMirror(models.Model):
    if TYPE_CHECKING:
        id: int = 0

    authentik_user_id: models.CharField[str, str] = models.CharField(
        max_length=128,
        unique=True,
    )
    name: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    email: models.EmailField[str, str] = models.EmailField(blank=True)
    avatar_url: models.CharField[str, str] = models.CharField(max_length=512, blank=True)
    department: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    status: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=USER_STATUS_CHOICES,
        default=USER_STATUS_ACTIVE,
    )
    dingtalk_source_slug: models.CharField[str, str] = models.CharField(
        max_length=128,
        blank=True,
    )
    dingtalk_union_id: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    dingtalk_userid: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    dingtalk_corp_id: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    employee_number: models.CharField[str, str] = models.CharField(max_length=64, blank=True)
    manager_userid: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    # EasyAuth 内控制台管理员的唯一落库标志, 与 Authentik 超管组检查取并集。
    # Authentik 组用于引导首位管理员; 本标志供管理员在控制台内授予/撤销。
    is_console_admin: models.BooleanField[bool, bool] = models.BooleanField(
        default=False,
        help_text="EasyAuth 内控制台管理员的唯一落库标志; 与 Authentik 超管组检查取并集。",
    )
    # 目录同步检出部门变更时置位, 供人员列表提示"部门已变更"(转岗线索, 不自动建单);
    # 转岗单确认后清除。
    department_changed_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["authentik_user_id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=(
                    (Q(dingtalk_source_slug="") & Q(dingtalk_corp_id="") & Q(dingtalk_userid=""))
                    | (
                        ~Q(dingtalk_source_slug="")
                        & ~Q(dingtalk_corp_id="")
                        & ~Q(dingtalk_userid="")
                    )
                ),
                name="accounts_user_dingtalk_binding_shape",
            ),
            models.UniqueConstraint(
                fields=["dingtalk_source_slug", "dingtalk_corp_id", "dingtalk_userid"],
                condition=(
                    ~Q(dingtalk_source_slug="") & ~Q(dingtalk_corp_id="") & ~Q(dingtalk_userid="")
                ),
                name="accounts_user_dingtalk_binding_unique",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["dingtalk_source_slug", "dingtalk_corp_id", "dingtalk_userid"],
                name="accounts_user_dingtalk_idx",
            ),
            models.Index(
                fields=["status", "updated_at", "id"],
                name="accounts_user_retention_idx",
            ),
        ]
        base_manager_name: ClassVar[str] = "objects"

    objects: ClassVar[UserMirrorManager] = UserMirrorManager()  # pyright: ignore[reportIncompatibleVariableOverride]

    @override
    def __str__(self) -> str:
        return self.authentik_user_id

    @override
    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError(USER_MIRROR_DELETE_ERROR)


class DingTalkDepartmentMirror(models.Model):
    source_slug: models.CharField[str, str] = models.CharField(max_length=128)
    corp_id: models.CharField[str, str] = models.CharField(max_length=128)
    dept_id: models.CharField[str, str] = models.CharField(max_length=128)
    parent_id: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    name: models.CharField[str, str] = models.CharField(max_length=128)
    order: models.IntegerField[int, int] = models.IntegerField(default=0)
    last_synced_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["source_slug", "corp_id", "dept_id"],
                name="accounts_dingtalk_dept_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["source_slug", "corp_id", "dept_id"]

    @override
    def __str__(self) -> str:
        return f"{self.source_slug}:{self.corp_id}:{self.dept_id}"


class DingTalkUserMirror(models.Model):
    source_slug: models.CharField[str, str] = models.CharField(max_length=128)
    corp_id: models.CharField[str, str] = models.CharField(max_length=128)
    user_id: models.CharField[str, str] = models.CharField(max_length=128)
    union_id: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    name: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    avatar: models.TextField[str, str] = models.TextField(blank=True, default="")
    title: models.CharField[str, str] = models.CharField(max_length=128, blank=True, default="")
    email: models.EmailField[str, str] = models.EmailField(blank=True, default="")
    mobile: models.CharField[str, str] = models.CharField(max_length=64, blank=True, default="")
    employee_number: models.CharField[str, str] = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )
    department_ids: models.JSONField[list[str], list[str]] = models.JSONField(default=list)
    manager_userid: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    status: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=USER_STATUS_CHOICES,
        default=USER_STATUS_ACTIVE,
    )
    # 上游权威快照中消失的员工不能物理删除: 保留身份与联系方式, 供下游识别离职。
    is_tombstone: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    last_seen_generation: models.BigIntegerField[int, int] = models.BigIntegerField(default=-1)
    departed_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    last_synced_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["source_slug", "corp_id", "user_id"],
                name="accounts_dingtalk_user_unique",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["source_slug", "corp_id", "manager_userid"],
                name="accounts_dt_user_manager_idx",
            ),
            models.Index(
                fields=["status", "departed_at", "id"],
                name="accounts_dt_user_retention_idx",
            ),
        ]
        ordering: ClassVar[list[str]] = ["source_slug", "corp_id", "user_id"]

    @override
    def __str__(self) -> str:
        return f"{self.source_slug}:{self.corp_id}:{self.user_id}"


class DingTalkUserOrgContext(models.Model):
    source_slug: models.CharField[str, str] = models.CharField(max_length=128)
    corp_id: models.CharField[str, str] = models.CharField(max_length=128)
    user_id: models.CharField[str, str] = models.CharField(max_length=128)
    departments: models.JSONField[list[JsonValue], list[JsonValue]] = models.JSONField(
        default=list,
    )
    manager: models.JSONField[dict[str, JsonValue], dict[str, JsonValue]] = models.JSONField(
        default=dict,
    )
    manager_chain: models.JSONField[list[JsonValue], list[JsonValue]] = models.JSONField(
        default=list,
    )
    stale: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    last_synced_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["source_slug", "corp_id", "user_id"],
                name="accounts_dingtalk_org_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["source_slug", "corp_id", "user_id"]

    @override
    def __str__(self) -> str:
        return f"{self.source_slug}:{self.corp_id}:{self.user_id}"


LOCAL_ADMIN_USERNAME_MAX_LENGTH: Final = 64
LOCAL_ADMIN_USERNAME_PATTERN: Final = r"^[a-z0-9][a-z0-9_-]*$"
LOCAL_ADMIN_USERNAME_ERROR: Final = (
    "用户名只允许小写字母、数字、连字符和下划线, 且以字母或数字开头。"
)


class LocalAdminAccount(models.Model):
    # 本地超级管理员账号: 不经 Authentik, 用密码 + 二次验证直接登录 console。
    if TYPE_CHECKING:
        id: ClassVar[int]
        passkeys: ClassVar[models.Manager[LocalAdminPasskey]]

    username: models.CharField[str, str] = models.CharField(
        max_length=LOCAL_ADMIN_USERNAME_MAX_LENGTH,
        unique=True,
        validators=[
            RegexValidator(LOCAL_ADMIN_USERNAME_PATTERN, LOCAL_ADMIN_USERNAME_ERROR),
        ],
    )
    password_hash: models.CharField[str, str] = models.CharField(max_length=255)
    # 首次登录/管理员重置后强制修改密码。
    must_change_password: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    # 会话绑定的单调版本。改密、停用账号或变更第二因子时递增, 使其他已签发会话失效。
    session_version: models.PositiveBigIntegerField[int, int] = models.PositiveBigIntegerField(
        default=1,
    )
    # TOTP 种子静态加密落库; 密文比 base32 明文长, 需更大的列宽。
    totp_secret: EncryptedCharField = EncryptedCharField(max_length=255, blank=True)
    totp_enabled: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    # 最近一次被接受的 TOTP timestep(counter); 拒绝 <= 该值的验证码, 实现一次性消费防重放。
    totp_last_timestep: models.BigIntegerField[int | None, int | None] = models.BigIntegerField(
        null=True,
        blank=True,
        default=None,
    )
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["username"]

    @override
    def __str__(self) -> str:
        return self.username

    @override
    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        effective_update_fields = None if update_fields is None else set(update_fields)
        if not self._state.adding:
            previous = (
                LocalAdminAccount.objects.filter(pk=self.pk)  # pyright: ignore[reportAny]
                .values(
                    "is_active",
                    "session_version",
                )
                .first()
            )
            if previous is not None and previous["is_active"] != self.is_active:
                self.session_version = int(previous["session_version"]) + 1  # pyright: ignore[reportAny]
                if effective_update_fields is not None:
                    effective_update_fields.add("session_version")
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=effective_update_fields,
        )

    def set_password(self, raw_password: str) -> None:
        self.password_hash = hashers.make_password(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return hashers.check_password(raw_password, self.password_hash)  # pyright: ignore[reportUnknownMemberType]

    def has_second_factor(self) -> bool:
        return self.totp_enabled or self.passkeys.exists()


class LocalAdminPasskey(models.Model):
    # 本地超管的 WebAuthn 通行密钥凭据; credential_id/public_key 均为 base64url 文本。
    if TYPE_CHECKING:
        id: ClassVar[int]

    account: models.ForeignKey[LocalAdminAccount, LocalAdminAccount] = models.ForeignKey(
        LocalAdminAccount,
        on_delete=models.CASCADE,
        related_name="passkeys",
    )
    credential_id: models.TextField[str, str] = models.TextField(unique=True)
    public_key: models.TextField[str, str] = models.TextField()
    sign_count: models.IntegerField[int, int] = models.IntegerField(default=0)
    transports: models.JSONField[list[str], list[str]] = models.JSONField(default=list)
    name: models.CharField[str, str] = models.CharField(max_length=100, blank=True)
    last_used_at: models.DateTimeField[date | datetime | None, datetime | None] = (
        models.DateTimeField(null=True, blank=True)
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["created_at", "id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(sign_count__gte=0),
                name="accounts_passkey_sc_gte_0",
            ),
        ]

    @override
    def __str__(self) -> str:
        return f"{self.account.username}:{self.name or self.credential_id[:12]}"


class DingTalkDirectorySyncState(models.Model):
    source_slug: models.CharField[str, str] = models.CharField(max_length=128)
    corp_id: models.CharField[str, str] = models.CharField(max_length=128)
    # 上游目录的单调快照代次。-1 仅表示本地尚未应用过任何权威快照;
    # 实际同步响应必须携带非负 generation。
    generation: models.BigIntegerField[int, int] = models.BigIntegerField(default=-1)
    status: models.CharField[str, str] = models.CharField(max_length=32, blank=True)
    counters: models.JSONField[dict[str, JsonValue], dict[str, JsonValue]] = models.JSONField(
        default=dict,
    )
    finished_at: models.CharField[str, str] = models.CharField(max_length=64, blank=True)
    error: models.TextField[str, str] = models.TextField(blank=True)
    last_synced_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["source_slug", "corp_id"],
                name="accounts_dingtalk_sync_unique",
            ),
        ]
        ordering: ClassVar[list[str]] = ["source_slug", "corp_id"]

    @override
    def __str__(self) -> str:
        return f"{self.source_slug}:{self.corp_id}:{self.status}"
