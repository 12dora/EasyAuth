from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, final, override

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

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

    def purge_created_before(self, cutoff: datetime, *, batch_size: int | None = None) -> int:
        # 保留期清理是唯一合法的删除口径; 其余路径保持只追加语义。
        expired = self.filter(created_at__lt=cutoff)
        if batch_size is not None:
            if batch_size <= 0:
                return 0
            ids = list(
                expired.order_by("created_at", "id").values_list("id", flat=True)[:batch_size],
            )
            expired = self.filter(id__in=ids)
        deleted_count, _ = models.QuerySet.delete(expired)  # pyright: ignore[reportUnknownMemberType]
        return deleted_count


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
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["created_at", "id"], name="audit_log_retention_idx"),
            models.Index(fields=["event_type", "-created_at", "-id"], name="audit_log_event_idx"),
            models.Index(
                fields=["actor_type", "actor_id", "-created_at"],
                name="audit_log_actor_idx",
            ),
            models.Index(
                fields=["target_type", "target_id", "-created_at"],
                name="audit_log_target_idx",
            ),
        ]

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


class DirectoryAuditBucket(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]

    app_key: models.CharField[str, str] = models.CharField(max_length=64)
    endpoint: models.CharField[str, str] = models.CharField(max_length=64)
    hour_bucket: models.CharField[str, str] = models.CharField(max_length=10)
    call_count: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    q_present: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    result_count: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    credential_id: models.CharField[str, str] = models.CharField(max_length=64, blank=True)
    flushed_at: models.DateTimeField[str | date | datetime | None, datetime | None] = (
        models.DateTimeField(blank=True, null=True)
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
                fields=["app_key", "endpoint", "hour_bucket"],
                name="audit_directory_bucket_unique",
            ),
            models.CheckConstraint(
                condition=Q(call_count__gte=0),
                name="audit_directory_bucket_call_count_non_negative",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["flushed_at", "hour_bucket", "id"],
                name="audit_dir_bucket_flush_idx",
            ),
        ]
        ordering: ClassVar[list[str]] = ["hour_bucket", "app_key", "endpoint"]

    @override
    def __str__(self) -> str:
        return f"{self.app_key}:{self.endpoint}:{self.hour_bucket}"
