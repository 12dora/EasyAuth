from __future__ import annotations

from datetime import timedelta
from typing import cast

import pytest
from django.db import connection
from django.utils import timezone

from easyauth.accounts.models import DingTalkUserMirror, UserMirror
from easyauth.applications.health_models import DependencyHealthSnapshot
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog
from easyauth.config import data_retention
from easyauth.integrations.models import DingTalkStreamEvent
from easyauth.webhooks.delivery import WebhookRedeliveryConflictError, redeliver
from easyauth.webhooks.models import WebhookDelivery

pytestmark = pytest.mark.django_db
SHA256_HEX_LENGTH = 64


def test_retention_cleanup_minimizes_profiles_and_raw_bodies() -> None:
    old = timezone.now() - timedelta(days=400)
    app = App.objects.create(app_key="retention-app", name="Retention")
    user = UserMirror.objects.create(
        authentik_user_id="retention-user",
        name="张三",
        email="zhang@example.com",
        avatar_url="https://avatar.example.com/1",
        department="研发部",
        status="departed",
        dingtalk_source_slug="dingtalk",
        dingtalk_union_id="union-1",
        dingtalk_userid="user-1",
        dingtalk_corp_id="corp-1",
        employee_number="E001",
        manager_userid="manager-1",
    )
    dingtalk_user = DingTalkUserMirror.objects.create(
        source_slug="dingtalk",
        corp_id="corp-1",
        user_id="user-1",
        union_id="union-1",
        name="张三",
        avatar="https://avatar.example.com/1",
        title="工程师",
        email="zhang@example.com",
        mobile="13800000000",
        employee_number="E001",
        department_ids=["1", "2"],
        manager_userid="manager-1",
        status="departed",
        departed_at=old,
    )
    stream = DingTalkStreamEvent.objects.create(
        event_id="retention-stream",
        event_type="user_leave_org",
        corp_id="corp-1",
        data={"mobile": "13800000000"},
        status="processed",
        processed_at=old,
    )
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="retention-delivery",
        event_type="approval.completed",
        target_url="https://app.example.com/hook",
        payload={"marker": "payload-sensitive-marker"},
        status="failed",
    )
    user_pk = cast("int", user.pk)
    delivery_pk = cast("int", delivery.pk)
    _ = UserMirror.objects.filter(pk=user_pk).update(updated_at=old)
    _ = WebhookDelivery.objects.filter(pk=delivery_pk).update(updated_at=old)

    result = data_retention.run_retention_cleanup(batch_size=10)

    user.refresh_from_db()
    dingtalk_user.refresh_from_db()
    stream.refresh_from_db()
    delivery.refresh_from_db()
    assert result.offboarding_profiles_minimized == 1
    assert result.dingtalk_profiles_minimized == 1
    assert result.stream_raw_bodies_minimized == 1
    assert result.webhook_raw_bodies_minimized == 1
    assert user.name == ""
    assert user.email == ""
    assert user.dingtalk_userid == "user-1"
    assert dingtalk_user.mobile == ""
    assert dingtalk_user.department_ids == []
    assert dingtalk_user.user_id == "user-1"
    assert stream.data == {}
    assert len(stream.data_sha256) == SHA256_HEX_LENGTH
    assert stream.data_minimized_at is not None
    assert delivery.payload == {}
    assert len(delivery.payload_sha256) == SHA256_HEX_LENGTH
    assert delivery.payload_minimized_at is not None


def test_retention_cleanup_keeps_retryable_raw_bodies_until_terminal_window() -> None:
    old = timezone.now() - timedelta(days=400)
    app = App.objects.create(app_key="retention-pending-app", name="Retention Pending")
    pending_delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="retention-pending-delivery",
        event_type="approval.completed",
        target_url="https://app.example.com/hook",
        payload={"still": "needed"},
        status="pending",
    )
    received_stream = DingTalkStreamEvent.objects.create(
        event_id="retention-received-stream",
        event_type="user_leave_org",
        corp_id="corp-1",
        data={"still": "needed"},
        status="received",
    )
    pending_delivery_pk = cast("int", pending_delivery.pk)
    received_stream_pk = cast("int", received_stream.pk)
    _ = WebhookDelivery.objects.filter(pk=pending_delivery_pk).update(updated_at=old)
    _ = DingTalkStreamEvent.objects.filter(pk=received_stream_pk).update(updated_at=old)

    result = data_retention.run_retention_cleanup(batch_size=10)

    pending_delivery.refresh_from_db()
    received_stream.refresh_from_db()
    assert result.webhook_raw_bodies_minimized == 0
    assert result.stream_raw_bodies_minimized == 0
    assert pending_delivery.payload == {"still": "needed"}
    assert received_stream.data == {"still": "needed"}


def test_minimized_webhook_payload_cannot_be_redelivered() -> None:
    app = App.objects.create(app_key="retention-redelivery-app", name="Retention Redelivery")
    delivery = WebhookDelivery.objects.create(
        app=app,
        delivery_id="retention-redelivery",
        event_type="approval.completed",
        target_url="https://app.example.com/hook",
        payload={},
        payload_sha256="0" * SHA256_HEX_LENGTH,
        payload_minimized_at=timezone.now(),
        status="failed",
    )

    with pytest.raises(WebhookRedeliveryConflictError, match="原文已超过保留窗口"):
        _ = redeliver(delivery)


def test_retention_cleanup_prunes_health_and_audit_in_batches() -> None:
    old = timezone.now() - timedelta(days=400)
    _ = DependencyHealthSnapshot.objects.create(
        dependency="authentik",
        status="healthy",
        checked_at=old,
        summary="旧健康",
    )
    audit = AuditLog.objects.create(
        actor_type="system",
        actor_id="retention",
        event_type="retention_old",
        target_type="retention",
        target_id="old",
        metadata={},
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE audit_auditlog SET created_at = %s WHERE id = %s",
            [old, cast("int", audit.pk)],
        )

    result = data_retention.run_retention_cleanup(batch_size=10)

    assert result.dependency_health_deleted == 1
    assert result.audit_logs_deleted == 1
    assert not DependencyHealthSnapshot.objects.exists()
    assert not AuditLog.objects.exists()
