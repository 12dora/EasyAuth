from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, override

from django.core.exceptions import ValidationError
from django.db import models

if TYPE_CHECKING:
    from datetime import date, datetime

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
