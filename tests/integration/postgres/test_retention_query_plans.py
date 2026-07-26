from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final, cast

import pytest
from django.db import connection
from django.utils import timezone

from easyauth.applications.health_models import DependencyHealthSnapshot
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog
from easyauth.integrations.models import DingTalkStreamEvent
from easyauth.webhooks.models import WebhookDelivery

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="PostgreSQL 查询计划证据只在 PostgreSQL lane 运行。",
    ),
]

BACKGROUND_ROW_COUNT: Final = 5_000
EXPIRED_ROW_COUNT: Final = 20


def test_retention_indexes_are_visible_to_postgresql_explain() -> None:
    cutoff = datetime(2000, 1, 1, tzinfo=timezone.get_current_timezone())
    _seed_selective_retention_rows(cutoff=cutoff)
    _analyze_retention_tables()

    plans = {
        "audit_log_retention_idx": AuditLog.objects.filter(created_at__lt=cutoff)
        .order_by("created_at", "id")[:500]
        .explain(),
        "app_dep_health_retention_idx": DependencyHealthSnapshot.objects.filter(
            checked_at__lt=cutoff,
        )
        .order_by("checked_at", "id")[:500]
        .explain(),
        "integr_stream_retention_idx": DingTalkStreamEvent.objects.filter(
            status="processed",
            data_minimized_at__isnull=True,
            processed_at__lt=cutoff,
        )
        .order_by("processed_at", "id")[:500]
        .explain(),
        "webhook_deliv_retention_idx": WebhookDelivery.objects.filter(
            status="failed",
            payload_minimized_at__isnull=True,
            updated_at__lt=cutoff,
        )
        .order_by("updated_at", "id")[:500]
        .explain(),
    }

    for index_name, plan in plans.items():
        assert index_name in plan


def _seed_selective_retention_rows(*, cutoff: datetime) -> None:
    old = cutoff - timedelta(days=1)
    future = timezone.now() + timedelta(days=1)
    app = App.objects.create(app_key="pg-retention-plan", name="PG Retention Plan")

    _ = AuditLog.objects.bulk_create(
        [
            AuditLog(
                actor_type="system",
                actor_id="pg-retention",
                event_type=f"future-{index}",
                target_type="retention",
                target_id=f"future-{index}",
                metadata={},
            )
            for index in range(BACKGROUND_ROW_COUNT)
        ],
    )
    expired_audits = AuditLog.objects.bulk_create(
        [
            AuditLog(
                actor_type="system",
                actor_id="pg-retention",
                event_type=f"expired-{index}",
                target_type="retention",
                target_id=f"expired-{index}",
                metadata={},
            )
            for index in range(EXPIRED_ROW_COUNT)
        ],
    )
    expired_audit_ids = [cast("int", audit.pk) for audit in expired_audits]
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE audit_auditlog SET created_at = %s WHERE id = ANY(%s)",
            [old, expired_audit_ids],
        )

    _ = DependencyHealthSnapshot.objects.bulk_create(
        [
            DependencyHealthSnapshot(
                dependency="authentik",
                status="healthy",
                checked_at=future,
                summary=f"future-{index}",
            )
            for index in range(BACKGROUND_ROW_COUNT)
        ],
    )
    _ = DependencyHealthSnapshot.objects.bulk_create(
        [
            DependencyHealthSnapshot(
                dependency="authentik",
                status="healthy",
                checked_at=old,
                summary=f"expired-{index}",
            )
            for index in range(EXPIRED_ROW_COUNT)
        ],
    )

    _ = DingTalkStreamEvent.objects.bulk_create(
        [
            DingTalkStreamEvent(
                event_id=f"pg-stream-future-{index}",
                event_type="user_leave_org",
                corp_id="corp-1",
                data={"index": index},
                status="processed",
                processed_at=future,
            )
            for index in range(BACKGROUND_ROW_COUNT)
        ],
    )
    _ = DingTalkStreamEvent.objects.bulk_create(
        [
            DingTalkStreamEvent(
                event_id=f"pg-stream-expired-{index}",
                event_type="user_leave_org",
                corp_id="corp-1",
                data={"index": index},
                status="processed",
                processed_at=old,
            )
            for index in range(EXPIRED_ROW_COUNT)
        ],
    )

    _ = WebhookDelivery.objects.bulk_create(
        [
            WebhookDelivery(
                app=app,
                delivery_id=f"pg-webhook-future-{index}",
                event_type="approval.completed",
                target_url="https://app.example.com/hook",
                payload={"index": index},
                status="delivered",
            )
            for index in range(BACKGROUND_ROW_COUNT)
        ],
    )
    _ = WebhookDelivery.objects.bulk_create(
        [
            WebhookDelivery(
                app=app,
                delivery_id=f"pg-webhook-expired-{index}",
                event_type="approval.completed",
                target_url="https://app.example.com/hook",
                payload={"index": index},
                status="failed",
            )
            for index in range(EXPIRED_ROW_COUNT)
        ],
    )
    _ = WebhookDelivery.objects.filter(delivery_id__startswith="pg-webhook-future-").update(
        updated_at=future,
    )
    _ = WebhookDelivery.objects.filter(delivery_id__startswith="pg-webhook-expired-").update(
        updated_at=old,
    )


def _analyze_retention_tables() -> None:
    with connection.cursor() as cursor:
        for table in (
            "audit_auditlog",
            "applications_dependencyhealthsnapshot",
            "integrations_dingtalkstreamevent",
            "webhooks_webhookdelivery",
        ):
            cursor.execute(f"ANALYZE {table}")
