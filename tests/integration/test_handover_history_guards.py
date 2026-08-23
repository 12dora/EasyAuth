"""交接投递与强行跳过永久史料的数据库约束。"""

from __future__ import annotations

import pytest
from django.db import connection, transaction
from django.db.utils import InternalError, ProgrammingError

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.lifecycle.models import (
    ACTION_STATUS_PENDING,
    BATCH_STATUS_EXECUTING,
    DELIVERY_OUTCOME_FAILED,
    DELIVERY_OUTCOME_SENT,
    DELIVERY_OUTCOME_SUCCEEDED,
    HANDOVER_KIND_OFFBOARD,
    HandoverActionSkipRecord,
    HandoverAppAction,
    HandoverDeliveryAttempt,
    HandoverExecutionBatch,
    HandoverTask,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="约束触发器只在 PostgreSQL lane 验证。",
    ),
]


def test_delivery_attempt_allows_one_transition_then_rejects_terminal_update() -> None:
    subject = UserMirror.objects.create(authentik_user_id="trg-delivery-sub")
    app = App.objects.create(app_key="trg-delivery-app", name="trg-delivery")
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        created_by="admin",
    )
    action = HandoverAppAction.objects.create(
        task=task,
        app=app,
        status=ACTION_STATUS_PENDING,
    )
    batch = HandoverExecutionBatch.objects.create(
        action=action,
        action_snapshot_id=action.id,
        generation=1,
        batch_seq=1,
        snapshot_token="snapshot",
        request_payload={"assignments": []},
        request_hash="0" * 64,
        status=BATCH_STATUS_EXECUTING,
        task_snapshot={"task_id": task.id},
    )
    delivery = HandoverDeliveryAttempt.objects.create(
        batch=batch,
        delivery_seq=1,
        lease_fence=1,
        outcome=DELIVERY_OUTCOME_SENT,
    )

    updated = HandoverDeliveryAttempt.objects.filter(pk=delivery.pk).update(
        outcome=DELIVERY_OUTCOME_SUCCEEDED,
        http_status=200,
    )
    assert updated == 1
    with pytest.raises((InternalError, ProgrammingError)), transaction.atomic():
        _ = HandoverDeliveryAttempt.objects.filter(pk=delivery.pk).update(
            outcome=DELIVERY_OUTCOME_FAILED,
            error_text="retry error",
        )


def _skip_record_fixture(prefix: str) -> tuple[HandoverTask, HandoverActionSkipRecord]:
    subject = UserMirror.objects.create(authentik_user_id=f"{prefix}-sub")
    app = App.objects.create(app_key=f"{prefix}-app", name=prefix)
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        created_by="admin",
    )
    action = HandoverAppAction.objects.create(
        task=task,
        app=app,
        status=ACTION_STATUS_PENDING,
    )
    record = HandoverActionSkipRecord.objects.create(
        task=task,
        task_id_snapshot=task.id,
        action_snapshot_id=action.id,
        generation=1,
        app_key=app.app_key,
        actor_id="admin",
        reason="永久原因",
    )
    return task, record


def test_skip_record_rejects_update_and_delete() -> None:
    _task, record = _skip_record_fixture("trg-skip-immutable")

    with pytest.raises((InternalError, ProgrammingError)), transaction.atomic():
        _ = HandoverActionSkipRecord.objects.filter(pk=record.pk).update(reason="篡改原因")
    with pytest.raises((InternalError, ProgrammingError)), transaction.atomic():
        _ = HandoverActionSkipRecord.objects.filter(pk=record.pk).delete()

    record.refresh_from_db()
    assert record.reason == "永久原因"


def test_task_delete_rejected_when_skip_snapshot_exists() -> None:
    task, _record = _skip_record_fixture("trg-task-skip")

    with (
        pytest.raises((InternalError, ProgrammingError)),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM lifecycle_handovertask WHERE id = %s", [task.id])

    assert HandoverTask.objects.filter(pk=task.pk).exists()
