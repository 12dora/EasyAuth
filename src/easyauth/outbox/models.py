from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, override

from django.db import models
from django.db.models import Q
from django.utils import timezone

if TYPE_CHECKING:
    from datetime import date, datetime

    from easyauth.applications.ops_models import JsonValue

OUTBOX_STATUS_PENDING: Final = "pending"
OUTBOX_STATUS_IN_FLIGHT: Final = "in_flight"
OUTBOX_STATUS_PUBLISHED: Final = "published"
OUTBOX_STATUS_VALUES: Final[tuple[str, ...]] = (
    OUTBOX_STATUS_PENDING,
    OUTBOX_STATUS_IN_FLIGHT,
    OUTBOX_STATUS_PUBLISHED,
)
OUTBOX_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (OUTBOX_STATUS_PENDING, "待发布"),
    (OUTBOX_STATUS_IN_FLIGHT, "发布中"),
    (OUTBOX_STATUS_PUBLISHED, "已发布"),
)


class OutboxEvent(models.Model):
    """与业务事实同事务写入、由独立 dispatcher 发布的 Celery 任务。"""

    if TYPE_CHECKING:
        id: ClassVar[int]

    event_key: models.CharField[str, str] = models.CharField(max_length=255, unique=True)
    task_name: models.CharField[str, str] = models.CharField(max_length=255)
    args: models.JSONField[list[JsonValue], list[JsonValue]] = models.JSONField(default=list)
    kwargs: models.JSONField[dict[str, JsonValue], dict[str, JsonValue]] = models.JSONField(
        default=dict,
    )
    status: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=OUTBOX_STATUS_CHOICES,
        default=OUTBOX_STATUS_PENDING,
    )
    attempts: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    available_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        default=timezone.now,
    )
    lease_token: models.CharField[str, str] = models.CharField(max_length=32, blank=True)
    lease_expires_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(null=True, blank=True)
    last_error: models.TextField[str, str] = models.TextField(blank=True)
    published_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(null=True, blank=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering: ClassVar[tuple[str, ...]] = ("created_at", "id")
        constraints: ClassVar[tuple[models.BaseConstraint, ...]] = (
            models.CheckConstraint(
                condition=Q(status__in=OUTBOX_STATUS_VALUES),
                name="outbox_status_supported",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status=OUTBOX_STATUS_PENDING,
                        lease_token="",
                        lease_expires_at__isnull=True,
                        published_at__isnull=True,
                    )
                    | Q(
                        status=OUTBOX_STATUS_IN_FLIGHT,
                        lease_token__gt="",
                        lease_expires_at__isnull=False,
                        last_error="",
                        published_at__isnull=True,
                    )
                    | Q(
                        status=OUTBOX_STATUS_PUBLISHED,
                        lease_token="",
                        lease_expires_at__isnull=True,
                        last_error="",
                        published_at__isnull=False,
                    )
                ),
                name="outbox_state_truth_shape",
            ),
        )
        indexes: ClassVar[tuple[models.Index, ...]] = (
            models.Index(
                fields=("status", "available_at"),
                name="outbox_status_available_idx",
            ),
            models.Index(
                fields=("status", "lease_expires_at"),
                name="outbox_status_lease_idx",
            ),
        )

    @override
    def __str__(self) -> str:
        return self.event_key
