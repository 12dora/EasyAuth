from __future__ import annotations

from django.db import models
from django.utils import timezone

OUTBOX_STATUS_PENDING = "pending"
OUTBOX_STATUS_IN_FLIGHT = "in_flight"
OUTBOX_STATUS_PUBLISHED = "published"
OUTBOX_STATUS_CHOICES = (
    (OUTBOX_STATUS_PENDING, "待发布"),
    (OUTBOX_STATUS_IN_FLIGHT, "发布中"),
    (OUTBOX_STATUS_PUBLISHED, "已发布"),
)


class OutboxEvent(models.Model):
    """与业务事实同事务写入、由独立 dispatcher 发布的 Celery 任务。"""

    event_key = models.CharField(max_length=255, unique=True)
    task_name = models.CharField(max_length=255)
    args = models.JSONField(default=list)
    kwargs = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16,
        choices=OUTBOX_STATUS_CHOICES,
        default=OUTBOX_STATUS_PENDING,
    )
    attempts = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now)
    lease_token = models.CharField(max_length=32, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = (
            models.Index(
                fields=("status", "available_at"),
                name="outbox_status_available_idx",
            ),
            models.Index(
                fields=("status", "lease_expires_at"),
                name="outbox_status_lease_idx",
            ),
        )

    def __str__(self) -> str:
        return self.event_key
