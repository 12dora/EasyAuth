from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, override

from django.contrib.auth import hashers
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

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


class UserMirror(models.Model):
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
    dingtalk_union_id: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    dingtalk_userid: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    dingtalk_corp_id: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    employee_number: models.CharField[str, str] = models.CharField(max_length=64, blank=True)
    manager_userid: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
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
    department_ids: models.JSONField[list[str], list[str]] = models.JSONField(default=list)
    manager_userid: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    status: models.CharField[str, str] = models.CharField(max_length=32, blank=True)
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
            previous = LocalAdminAccount.objects.filter(pk=self.pk).values(
                "is_active",
                "session_version",
            ).first()
            if previous is not None and previous["is_active"] != self.is_active:
                self.session_version = int(previous["session_version"]) + 1
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
        return hashers.check_password(raw_password, self.password_hash)

    def has_second_factor(self) -> bool:
        return self.totp_enabled or self.passkeys.exists()


class LocalAdminPasskey(models.Model):
    # 本地超管的 WebAuthn 通行密钥凭据; credential_id/public_key 均为 base64url 文本。
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
