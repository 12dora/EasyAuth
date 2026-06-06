from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, Protocol, override

from django.db import models
from django.db.models import Q
from django.utils import timezone

if TYPE_CHECKING:
    from datetime import date, datetime

DEPENDENCY_AUTHENTIK: Final = "authentik"
DEPENDENCY_DINGTALK: Final = "dingtalk"
DEPENDENCY_CELERY: Final = "celery"
DEPENDENCY_HEALTH_DEPENDENCY_VALUES: Final[tuple[str, ...]] = (
    DEPENDENCY_AUTHENTIK,
    DEPENDENCY_DINGTALK,
    DEPENDENCY_CELERY,
)
DEPENDENCY_HEALTH_DEPENDENCY_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (DEPENDENCY_AUTHENTIK, "authentik"),
    (DEPENDENCY_DINGTALK, "dingtalk"),
    (DEPENDENCY_CELERY, "celery"),
)
DEPENDENCY_HEALTH_STATUS_HEALTHY: Final = "healthy"
DEPENDENCY_HEALTH_STATUS_WARNING: Final = "warning"
DEPENDENCY_HEALTH_STATUS_UNHEALTHY: Final = "unhealthy"
DEPENDENCY_HEALTH_STATUS_UNKNOWN: Final = "unknown"
DEPENDENCY_HEALTH_STATUS_VALUES: Final[tuple[str, ...]] = (
    DEPENDENCY_HEALTH_STATUS_HEALTHY,
    DEPENDENCY_HEALTH_STATUS_WARNING,
    DEPENDENCY_HEALTH_STATUS_UNHEALTHY,
    DEPENDENCY_HEALTH_STATUS_UNKNOWN,
)
DEPENDENCY_HEALTH_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (DEPENDENCY_HEALTH_STATUS_HEALTHY, "healthy"),
    (DEPENDENCY_HEALTH_STATUS_WARNING, "warning"),
    (DEPENDENCY_HEALTH_STATUS_UNHEALTHY, "unhealthy"),
    (DEPENDENCY_HEALTH_STATUS_UNKNOWN, "unknown"),
)


class _BoundApp(Protocol):
    id: int
    app_key: str


class DependencyHealthSnapshot(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]
        app_id: ClassVar[int | None]

    app: models.ForeignKey[_BoundApp | None, _BoundApp | None] = models.ForeignKey(
        "applications.App",
        on_delete=models.CASCADE,
        related_name="dependency_health_snapshots",
        blank=True,
        null=True,
    )
    dependency: models.CharField[str, str] = models.CharField(
        max_length=64,
        choices=DEPENDENCY_HEALTH_DEPENDENCY_CHOICES,
    )
    status: models.CharField[str, str] = models.CharField(
        max_length=32,
        choices=DEPENDENCY_HEALTH_STATUS_CHOICES,
        default=DEPENDENCY_HEALTH_STATUS_UNKNOWN,
    )
    checked_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        default=timezone.now,
    )
    summary: models.TextField[str, str] = models.TextField(blank=True)
    error_summary: models.TextField[str, str] = models.TextField(blank=True)
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(dependency__in=DEPENDENCY_HEALTH_DEPENDENCY_VALUES),
                name="applications_dependency_health_dependency_supported",
            ),
            models.CheckConstraint(
                condition=Q(status__in=DEPENDENCY_HEALTH_STATUS_VALUES),
                name="applications_dependency_health_status_supported",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["dependency", "-checked_at", "-id"],
                name="app_dep_health_latest_idx",
            ),
        ]
        ordering: ClassVar[list[str]] = ["dependency", "-checked_at", "-id"]

    @override
    def __str__(self) -> str:
        return f"{self.dependency}:{self.status}:{self.checked_at.isoformat()}"
