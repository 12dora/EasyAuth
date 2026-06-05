from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, final, override

from django.core.exceptions import ValidationError
from django.db import models

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date, datetime

    from django.db.models.base import ModelBase

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

AUDIT_LOG_UPDATE_ERROR: Final = "AuditLog is append-only and cannot be updated."
AUDIT_LOG_DELETE_ERROR: Final = "AuditLog is append-only and cannot be deleted."


class AuditLogQuerySet(models.QuerySet["AuditLog"]):
    @override
    def update(self, **kwargs: JsonValue) -> int:
        raise ValidationError(AUDIT_LOG_UPDATE_ERROR)

    @override
    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValidationError(AUDIT_LOG_DELETE_ERROR)


@final
class AuditLog(models.Model):
    objects = AuditLogQuerySet.as_manager()
    actor_type: models.CharField[str, str] = models.CharField(max_length=32)
    actor_id: models.CharField[str, str] = models.CharField(max_length=128)
    event_type: models.CharField[str, str] = models.CharField(max_length=128)
    target_type: models.CharField[str, str] = models.CharField(max_length=64)
    target_id: models.CharField[str, str] = models.CharField(max_length=128)
    metadata: models.JSONField[JsonObject, JsonObject] = models.JSONField(default=dict)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]

    @override
    def __str__(self) -> str:
        return f"{self.event_type}:{self.target_type}:{self.target_id}"

    @override
    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if not self._state.adding:
            raise ValidationError(AUDIT_LOG_UPDATE_ERROR)
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    @override
    def delete(
        self,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        raise ValidationError(AUDIT_LOG_DELETE_ERROR)
