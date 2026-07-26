from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from json import dumps
from typing import Final, cast

from django.db import transaction
from django.utils import timezone

from easyauth.accounts.models import (
    USER_STATUS_DEPARTED,
    DingTalkUserMirror,
    UserMirror,
)
from easyauth.applications.health_models import DependencyHealthSnapshot
from easyauth.audit.directory_audit import flush_directory_audit_buckets
from easyauth.audit.models import AuditLog, AuditLogQuerySet
from easyauth.integrations.models import (
    STREAM_EVENT_STATUS_FAILED,
    STREAM_EVENT_STATUS_PROCESSED,
    STREAM_EVENT_STATUS_SKIPPED,
    DingTalkStreamEvent,
)
from easyauth.webhooks.models import (
    DELIVERY_STATUS_DELIVERED,
    DELIVERY_STATUS_FAILED,
    WebhookDelivery,
)

OFFBOARDING_PROFILE_RETENTION_DAYS: Final = 30
STREAM_RAW_BODY_RETENTION_DAYS: Final = 30
WEBHOOK_RAW_BODY_RETENTION_DAYS: Final = 7
DEPENDENCY_HEALTH_RETENTION_DAYS: Final = 30
AUDIT_LOG_RETENTION_DAYS: Final = 365
RETENTION_CLEANUP_BATCH_SIZE: Final = 500


@dataclass(frozen=True, slots=True)
class RetentionCleanupResult:
    offboarding_profiles_minimized: int = 0
    dingtalk_profiles_minimized: int = 0
    stream_raw_bodies_minimized: int = 0
    webhook_raw_bodies_minimized: int = 0
    dependency_health_deleted: int = 0
    audit_logs_deleted: int = 0
    directory_audit_buckets_flushed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "offboarding_profiles_minimized": self.offboarding_profiles_minimized,
            "dingtalk_profiles_minimized": self.dingtalk_profiles_minimized,
            "stream_raw_bodies_minimized": self.stream_raw_bodies_minimized,
            "webhook_raw_bodies_minimized": self.webhook_raw_bodies_minimized,
            "dependency_health_deleted": self.dependency_health_deleted,
            "audit_logs_deleted": self.audit_logs_deleted,
            "directory_audit_buckets_flushed": self.directory_audit_buckets_flushed,
        }


def run_retention_cleanup(
    *,
    batch_size: int = RETENTION_CLEANUP_BATCH_SIZE,
) -> RetentionCleanupResult:
    if batch_size <= 0:
        return RetentionCleanupResult()
    return RetentionCleanupResult(
        offboarding_profiles_minimized=minimize_offboarding_profiles(batch_size=batch_size),
        dingtalk_profiles_minimized=minimize_dingtalk_departed_profiles(batch_size=batch_size),
        stream_raw_bodies_minimized=minimize_stream_raw_bodies(batch_size=batch_size),
        webhook_raw_bodies_minimized=minimize_webhook_raw_bodies(batch_size=batch_size),
        dependency_health_deleted=prune_dependency_health_history(batch_size=batch_size),
        directory_audit_buckets_flushed=flush_directory_audit_buckets(
            batch_size=batch_size,
        ).flushed_count,
        audit_logs_deleted=prune_audit_logs_by_retention(batch_size=batch_size),
    )


def minimize_offboarding_profiles(*, batch_size: int = RETENTION_CLEANUP_BATCH_SIZE) -> int:
    cutoff = timezone.now() - timedelta(days=OFFBOARDING_PROFILE_RETENTION_DAYS)
    users = list(
        UserMirror.objects.filter(status=USER_STATUS_DEPARTED, updated_at__lt=cutoff)
        .exclude(
            name="",
            email="",
            avatar_url="",
            department="",
            employee_number="",
            manager_userid="",
            dingtalk_union_id="",
        )
        .order_by("updated_at", "id")[:batch_size],
    )
    for user in users:
        user.name = ""
        user.email = ""
        user.avatar_url = ""
        user.department = ""
        user.employee_number = ""
        user.manager_userid = ""
        user.dingtalk_union_id = ""
        user.save(
            update_fields=[
                "name",
                "email",
                "avatar_url",
                "department",
                "employee_number",
                "manager_userid",
                "dingtalk_union_id",
                "updated_at",
            ],
        )
    return len(users)


def minimize_dingtalk_departed_profiles(*, batch_size: int = RETENTION_CLEANUP_BATCH_SIZE) -> int:
    cutoff = timezone.now() - timedelta(days=OFFBOARDING_PROFILE_RETENTION_DAYS)
    users = list(
        DingTalkUserMirror.objects.filter(status=USER_STATUS_DEPARTED, departed_at__lt=cutoff)
        .exclude(
            name="",
            avatar="",
            title="",
            email="",
            mobile="",
            employee_number="",
            department_ids=[],
            manager_userid="",
            union_id="",
        )
        .order_by("departed_at", "id")[:batch_size],
    )
    for user in users:
        user.name = ""
        user.avatar = ""
        user.title = ""
        user.email = ""
        user.mobile = ""
        user.employee_number = ""
        user.department_ids = []
        user.manager_userid = ""
        user.union_id = ""
        user.save(
            update_fields=[
                "name",
                "avatar",
                "title",
                "email",
                "mobile",
                "employee_number",
                "department_ids",
                "manager_userid",
                "union_id",
                "last_synced_at",
            ],
        )
    return len(users)


def minimize_stream_raw_bodies(*, batch_size: int = RETENTION_CLEANUP_BATCH_SIZE) -> int:
    cutoff = timezone.now() - timedelta(days=STREAM_RAW_BODY_RETENTION_DAYS)
    events = list(
        DingTalkStreamEvent.objects.filter(
            status__in=(
                STREAM_EVENT_STATUS_PROCESSED,
                STREAM_EVENT_STATUS_SKIPPED,
                STREAM_EVENT_STATUS_FAILED,
            ),
            processed_at__lt=cutoff,
            data_minimized_at__isnull=True,
        )
        .exclude(data={})
        .order_by("processed_at", "id")[:batch_size],
    )
    now = timezone.now()
    for event in events:
        event.data_sha256 = _json_sha256(event.data)
        event.data = {}
        event.data_minimized_at = now
        event.save(update_fields=["data", "data_sha256", "data_minimized_at", "updated_at"])
    return len(events)


def minimize_webhook_raw_bodies(*, batch_size: int = RETENTION_CLEANUP_BATCH_SIZE) -> int:
    cutoff = timezone.now() - timedelta(days=WEBHOOK_RAW_BODY_RETENTION_DAYS)
    deliveries = list(
        WebhookDelivery.objects.filter(
            status__in=(DELIVERY_STATUS_DELIVERED, DELIVERY_STATUS_FAILED),
            updated_at__lt=cutoff,
            payload_minimized_at__isnull=True,
        )
        .exclude(payload={})
        .order_by("updated_at", "id")[:batch_size],
    )
    now = timezone.now()
    for delivery in deliveries:
        delivery.payload_sha256 = _json_sha256(delivery.payload)
        delivery.payload = {}
        delivery.payload_minimized_at = now
        delivery.save(
            update_fields=["payload", "payload_sha256", "payload_minimized_at", "updated_at"],
        )
    return len(deliveries)


def prune_dependency_health_history(*, batch_size: int = RETENTION_CLEANUP_BATCH_SIZE) -> int:
    cutoff = timezone.now() - timedelta(days=DEPENDENCY_HEALTH_RETENTION_DAYS)
    ids = list(
        DependencyHealthSnapshot.objects.filter(checked_at__lt=cutoff)
        .order_by("checked_at", "id")
        .values_list("id", flat=True)[:batch_size],
    )
    if not ids:
        return 0
    deleted_count, _ = DependencyHealthSnapshot.objects.filter(id__in=ids).delete()
    return deleted_count


def prune_audit_logs_by_retention(*, batch_size: int = RETENTION_CLEANUP_BATCH_SIZE) -> int:
    cutoff = timezone.now() - timedelta(days=AUDIT_LOG_RETENTION_DAYS)
    queryset = cast("AuditLogQuerySet", AuditLog.objects.all())
    with transaction.atomic():
        return queryset.purge_created_before(cutoff, batch_size=batch_size)


def _json_sha256(value: object) -> str:
    canonical = dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
