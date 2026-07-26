from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from django.db import IntegrityError, connection, transaction
from django.db.models import F
from django.utils import timezone

from easyauth.audit.models import DirectoryAuditBucket
from easyauth.audit.services import AuditRecord, AuditService

DIRECTORY_AUDIT_ACTION: Final = "app_directory_queried"
DIRECTORY_AUDIT_TARGET_TYPE: Final = "directory"
DIRECTORY_AUDIT_BUCKET_FORMAT: Final = "%Y%m%d%H"


@dataclass(frozen=True, slots=True)
class DirectoryAuditFlushResult:
    flushed_count: int


def record_directory_audit_bucket(
    *,
    app_key: str,
    endpoint: str,
    result_count: int,
    q_present: bool,
    credential_id: str | int,
) -> None:
    hour_bucket = timezone.now().strftime(DIRECTORY_AUDIT_BUCKET_FORMAT)
    credential = str(credential_id)
    updated = DirectoryAuditBucket.objects.filter(
        app_key=app_key,
        endpoint=endpoint,
        hour_bucket=hour_bucket,
        flushed_at__isnull=True,
    ).update(
        call_count=F("call_count") + 1,
        q_present=True if q_present else F("q_present"),
        result_count=result_count,
        credential_id=credential,
    )
    if updated:
        return
    try:
        _ = DirectoryAuditBucket.objects.create(
            app_key=app_key,
            endpoint=endpoint,
            hour_bucket=hour_bucket,
            call_count=1,
            q_present=q_present,
            result_count=result_count,
            credential_id=credential,
        )
    except IntegrityError:
        _ = DirectoryAuditBucket.objects.filter(
            app_key=app_key,
            endpoint=endpoint,
            hour_bucket=hour_bucket,
            flushed_at__isnull=True,
        ).update(
            call_count=F("call_count") + 1,
            q_present=True if q_present else F("q_present"),
            result_count=result_count,
            credential_id=credential,
        )


def flush_directory_audit_buckets(
    *,
    batch_size: int,
) -> DirectoryAuditFlushResult:
    if batch_size <= 0:
        return DirectoryAuditFlushResult(flushed_count=0)
    current_hour = timezone.now().strftime(DIRECTORY_AUDIT_BUCKET_FORMAT)
    queryset = DirectoryAuditBucket.objects.filter(
        flushed_at__isnull=True,
        hour_bucket__lt=current_hour,
    ).order_by("hour_bucket", "id")
    if connection.features.has_select_for_update_skip_locked:
        queryset = queryset.select_for_update(skip_locked=True)
    else:
        queryset = queryset.select_for_update()
    flushed = 0
    with transaction.atomic():
        buckets = tuple(queryset[:batch_size])
        flushed_at = timezone.now()
        for bucket in buckets:
            _ = AuditService.record(
                AuditRecord(
                    actor_type="app",
                    actor_id=bucket.app_key,
                    action=DIRECTORY_AUDIT_ACTION,
                    target_type=DIRECTORY_AUDIT_TARGET_TYPE,
                    target_id=bucket.app_key,
                    metadata={
                        "endpoint": bucket.endpoint,
                        "q_present": bucket.q_present,
                        "result_count": bucket.result_count,
                        "credential_id": bucket.credential_id,
                        "call_count": bucket.call_count,
                        "hour_bucket": bucket.hour_bucket,
                    },
                ),
            )
            bucket.flushed_at = flushed_at
            bucket.save(update_fields=["flushed_at", "updated_at"])
            flushed += 1
    return DirectoryAuditFlushResult(flushed_count=flushed)
