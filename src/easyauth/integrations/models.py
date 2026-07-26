from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, override

from django.db import models
from django.db.models import Q

if TYPE_CHECKING:
    from datetime import date, datetime

    from easyauth.applications.ops_models import JsonValue

# 钉钉 Stream 事件收件箱状态机: received(已落库待处理) → processed(已按事件类型处理) /
# skipped(记录在案但无需处理) / failed(处理失败, 错误原样落库待人工介入)。
STREAM_EVENT_STATUS_RECEIVED: Final = "received"
STREAM_EVENT_STATUS_PROCESSED: Final = "processed"
STREAM_EVENT_STATUS_SKIPPED: Final = "skipped"
STREAM_EVENT_STATUS_FAILED: Final = "failed"
STREAM_EVENT_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (STREAM_EVENT_STATUS_RECEIVED, "received"),
    (STREAM_EVENT_STATUS_PROCESSED, "processed"),
    (STREAM_EVENT_STATUS_SKIPPED, "skipped"),
    (STREAM_EVENT_STATUS_FAILED, "failed"),
)
STREAM_EVENT_STATUS_VALUES: Final[tuple[str, ...]] = tuple(
    value for value, _label in STREAM_EVENT_STATUS_CHOICES
)


class DingTalkStreamEvent(models.Model):
    """钉钉 Stream 推送事件的持久化收件箱。

    每条事件先落库再 ACK: 钉钉侧以 event_id 去重重投, 本表以 event_id 唯一约束幂等,
    处理结果与错误都回写本行, 使人员入离职等事件有可审计的完整接收/处理轨迹。
    """

    event_id: models.CharField[str, str] = models.CharField(max_length=128, unique=True)
    event_type: models.CharField[str, str] = models.CharField(max_length=128, db_index=True)
    corp_id: models.CharField[str, str] = models.CharField(max_length=128, blank=True, default="")
    born_at: models.DateTimeField[str | date | datetime | None, datetime | None] = (
        models.DateTimeField(null=True, blank=True)
    )
    data: models.JSONField[dict[str, JsonValue], dict[str, JsonValue]] = models.JSONField(
        default=dict,
        blank=True,
    )
    data_sha256: models.CharField[str, str] = models.CharField(
        max_length=64,
        blank=True,
        default="",
    )
    data_minimized_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(null=True, blank=True)
    status: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=STREAM_EVENT_STATUS_CHOICES,
        default=STREAM_EVENT_STATUS_RECEIVED,
        db_index=True,
    )
    result: models.JSONField[dict[str, JsonValue], dict[str, JsonValue]] = models.JSONField(
        default=dict,
        blank=True,
    )
    error: models.TextField[str, str] = models.TextField(blank=True, default="")
    processed_at: models.DateTimeField[str | date | datetime | None, datetime | None] = (
        models.DateTimeField(null=True, blank=True)
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(status__in=STREAM_EVENT_STATUS_VALUES),
                name="integrations_stream_status_supported",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status=STREAM_EVENT_STATUS_RECEIVED,
                        processed_at__isnull=True,
                        error="",
                    )
                    | Q(
                        status__in=(
                            STREAM_EVENT_STATUS_PROCESSED,
                            STREAM_EVENT_STATUS_SKIPPED,
                        ),
                        processed_at__isnull=False,
                        error="",
                    )
                    | Q(
                        status=STREAM_EVENT_STATUS_FAILED,
                        processed_at__isnull=False,
                        error__gt="",
                    )
                ),
                name="integrations_stream_state_shape",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["status", "data_minimized_at", "processed_at", "id"],
                name="integr_stream_retention_idx",
            ),
            models.Index(
                fields=["event_type", "-created_at", "-id"],
                name="integr_stream_event_type_idx",
            ),
        ]
        ordering: ClassVar[list[str]] = ["-created_at"]

    @override
    def __str__(self) -> str:
        return f"{self.event_type}:{self.event_id}"
