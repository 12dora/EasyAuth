from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, override

from django.core.exceptions import ValidationError
from django.db import models

if TYPE_CHECKING:
    from datetime import date, datetime

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


class DingTalkDirectorySyncState(models.Model):
    source_slug: models.CharField[str, str] = models.CharField(max_length=128)
    corp_id: models.CharField[str, str] = models.CharField(max_length=128)
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
