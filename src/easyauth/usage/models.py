from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, override

from django.db import models
from django.db.models import Q

from easyauth.usage.registry import (
    CATEGORY_KEYS,
    USAGE_METRIC_VALUES,
    USAGE_SOURCE_VALUES,
)

if TYPE_CHECKING:
    from datetime import date, datetime

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]

USAGE_SETTINGS_SINGLETON_ID: Final = 1
USAGE_RUNTIME_STATE_SINGLETON_ID: Final = 1

USAGE_METRIC_CHOICES: Final[tuple[tuple[str, str], ...]] = tuple(
    (item, item) for item in USAGE_METRIC_VALUES
)
USAGE_SOURCE_CHOICES: Final[tuple[tuple[str, str], ...]] = tuple(
    (item, item) for item in USAGE_SOURCE_VALUES
)

USAGE_ALERT_KIND_THRESHOLD: Final = "threshold"
USAGE_ALERT_KIND_ANOMALY: Final = "anomaly"
USAGE_ALERT_KIND_ENFORCEMENT: Final = "enforcement"
USAGE_ALERT_KIND_STREAM_PAUSED: Final = "stream_paused"
USAGE_ALERT_KIND_STREAM_RESUMED: Final = "stream_resumed"
USAGE_ALERT_KIND_VALUES: Final[tuple[str, ...]] = (
    USAGE_ALERT_KIND_THRESHOLD,
    USAGE_ALERT_KIND_ANOMALY,
    USAGE_ALERT_KIND_ENFORCEMENT,
    USAGE_ALERT_KIND_STREAM_PAUSED,
    USAGE_ALERT_KIND_STREAM_RESUMED,
)
USAGE_ALERT_KIND_CHOICES: Final[tuple[tuple[str, str], ...]] = tuple(
    (item, item) for item in USAGE_ALERT_KIND_VALUES
)

USAGE_ALERT_SCOPE_DAY: Final = "day"
USAGE_ALERT_SCOPE_MONTH: Final = "month"
USAGE_ALERT_SCOPE_HOUR: Final = "hour"
USAGE_ALERT_SCOPE_VALUES: Final[tuple[str, ...]] = (
    USAGE_ALERT_SCOPE_DAY,
    USAGE_ALERT_SCOPE_MONTH,
    USAGE_ALERT_SCOPE_HOUR,
)
USAGE_ALERT_SCOPE_CHOICES: Final[tuple[tuple[str, str], ...]] = tuple(
    (item, item) for item in USAGE_ALERT_SCOPE_VALUES
)

USAGE_ALERT_STATUS_SENT: Final = "sent"
USAGE_ALERT_STATUS_SUPPRESSED: Final = "suppressed"
USAGE_ALERT_STATUS_SUPERSEDED: Final = "superseded"
USAGE_ALERT_STATUS_FAILED: Final = "failed"
USAGE_ALERT_STATUS_VALUES: Final[tuple[str, ...]] = (
    USAGE_ALERT_STATUS_SENT,
    USAGE_ALERT_STATUS_SUPPRESSED,
    USAGE_ALERT_STATUS_SUPERSEDED,
    USAGE_ALERT_STATUS_FAILED,
)
USAGE_ALERT_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = tuple(
    (item, item) for item in USAGE_ALERT_STATUS_VALUES
)


class UsageBucket(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]

    hour_start: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField()
    source: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=USAGE_SOURCE_CHOICES,
    )
    category: models.CharField[str, str] = models.CharField(max_length=64)
    metric: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=USAGE_METRIC_CHOICES,
    )
    billed: models.BooleanField[bool, bool] = models.BooleanField()
    count: models.PositiveBigIntegerField[int, int] = models.PositiveBigIntegerField(default=0)
    blocked_count: models.PositiveBigIntegerField[int, int] = models.PositiveBigIntegerField(
        default=0,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["hour_start", "source", "category"],
                name="usage_bucket_hour_source_cat_uniq",
            ),
            models.CheckConstraint(
                condition=Q(source__in=USAGE_SOURCE_VALUES),
                name="usage_bucket_source_supported",
            ),
            models.CheckConstraint(
                condition=Q(metric__in=USAGE_METRIC_VALUES),
                name="usage_bucket_metric_supported",
            ),
            models.CheckConstraint(
                condition=Q(category__in=CATEGORY_KEYS),
                name="usage_bucket_category_supported",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["hour_start"], name="usage_bucket_hour_idx"),
            models.Index(fields=["metric", "hour_start"], name="usage_bucket_metric_hour_idx"),
        ]
        ordering: ClassVar[list[str]] = ["hour_start", "source", "category"]

    @override
    def __str__(self) -> str:
        return f"{self.source}:{self.category}:{self.hour_start:%Y-%m-%d %H}"


class UsageSettings(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]

    config: models.JSONField[JsonObject, JsonObject] = models.JSONField(default=dict)
    version: models.PositiveIntegerField[int, int] = models.PositiveIntegerField(default=0)
    updated_by: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(id=USAGE_SETTINGS_SINGLETON_ID),
                name="usage_settings_singleton",
            ),
        ]

    @override
    def __str__(self) -> str:
        return f"usage-settings:{self.id}"

    @classmethod
    def load(cls) -> UsageSettings:
        row, _created = cls.objects.get_or_create(pk=USAGE_SETTINGS_SINGLETON_ID)
        return row


class UsageRuntimeState(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]

    enforcement: models.JSONField[JsonObject, JsonObject] = models.JSONField(default=dict)
    evaluated_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    stream_paused: models.BooleanField[bool, bool] = models.BooleanField(default=False)
    stream_paused_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    stream_paused_period: models.CharField[str, str] = models.CharField(max_length=32, blank=True)
    stream_manual_resume_period: models.CharField[str, str] = models.CharField(
        max_length=32,
        blank=True,
    )
    authentik_pulled_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    authentik_policy_pushed_at: models.DateTimeField[
        str | date | datetime | None,
        datetime | None,
    ] = models.DateTimeField(blank=True, null=True)
    authentik_error: models.TextField[str, str] = models.TextField(blank=True)

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(id=USAGE_RUNTIME_STATE_SINGLETON_ID),
                name="usage_runtime_state_singleton",
            ),
        ]

    @override
    def __str__(self) -> str:
        return f"usage-runtime-state:{self.id}"

    @classmethod
    def load(cls) -> UsageRuntimeState:
        row, _created = cls.objects.get_or_create(pk=USAGE_RUNTIME_STATE_SINGLETON_ID)
        return row


class UsageAlertEvent(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]

    kind: models.CharField[str, str] = models.CharField(
        max_length=32,
        choices=USAGE_ALERT_KIND_CHOICES,
    )
    metric: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=USAGE_METRIC_CHOICES,
    )
    scope: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=USAGE_ALERT_SCOPE_CHOICES,
    )
    period_key: models.CharField[str, str] = models.CharField(max_length=32)
    threshold_percent: models.PositiveSmallIntegerField[int, int] = (
        models.PositiveSmallIntegerField(default=0)
    )
    status: models.CharField[str, str] = models.CharField(
        max_length=16,
        choices=USAGE_ALERT_STATUS_CHOICES,
    )
    title: models.CharField[str, str] = models.CharField(max_length=255)
    detail: models.TextField[str, str] = models.TextField()
    failure_reason: models.TextField[str, str] = models.TextField(blank=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["kind", "metric", "scope", "period_key", "threshold_percent"],
                name="usage_alert_event_dedupe",
            ),
            models.CheckConstraint(
                condition=Q(kind__in=USAGE_ALERT_KIND_VALUES),
                name="usage_alert_kind_supported",
            ),
            models.CheckConstraint(
                condition=Q(metric__in=USAGE_METRIC_VALUES),
                name="usage_alert_metric_supported",
            ),
            models.CheckConstraint(
                condition=Q(scope__in=USAGE_ALERT_SCOPE_VALUES),
                name="usage_alert_scope_supported",
            ),
            models.CheckConstraint(
                condition=Q(status__in=USAGE_ALERT_STATUS_VALUES),
                name="usage_alert_status_supported",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["created_at", "id"], name="usage_alert_retention_idx"),
        ]
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]

    @override
    def __str__(self) -> str:
        return f"{self.kind}:{self.metric}:{self.period_key}:{self.threshold_percent}"
