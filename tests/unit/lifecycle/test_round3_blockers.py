"""Round-3 blocker/major regression pins for A1c."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from django.utils import timezone

from easyauth.accounts.models import USER_STATUS_ACTIVE, USER_STATUS_DEPARTED, UserMirror
from easyauth.applications.models import App
from easyauth.lifecycle.errors import HandoverError
from easyauth.lifecycle.handover import (
    _ensure_batch_plan_on_413,
    _handle_execute_response,
    async_abandon_action,
    complete_data_phase,
    execute_action,
    retry_action,
    update_grant_receiver,
    validate_execute_summary_conservation,
)
from easyauth.lifecycle.lease import LeaseHandle, take_lease
from easyauth.lifecycle.models import (
    ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    ACTION_STATUS_DONE,
    ACTION_STATUS_EXECUTING,
    ACTION_STATUS_FAILED,
    ACTION_STATUS_PREVIEWED,
    BATCH_PLAN_STATUS_ACTIVE,
    BATCH_PLAN_STATUS_DONE,
    BATCH_STATUS_ASYNC_PENDING,
    BATCH_STATUS_DATA_COMPLETED,
    BATCH_STATUS_DONE,
    BATCH_STATUS_EXECUTING,
    BATCH_STATUS_FAILED,
    DELIVERY_OUTCOME_FAILED,
    DELIVERY_OUTCOME_SENT,
    HANDOVER_KIND_OFFBOARD,
    HandoverAppAction,
    HandoverAssetType,
    HandoverBatchPlan,
    HandoverDeliveryAttempt,
    HandoverExecutionBatch,
    HandoverExecutionLease,
    HandoverTask,
)
from easyauth.webhooks.hooks import HookResponse
from easyauth.webhooks.models import AppWebhookConfig

pytestmark = pytest.mark.django_db


def _subject_app_action(
    *,
    status: str = ACTION_STATUS_PREVIEWED,
    count: int = 10,
) -> tuple[UserMirror, App, HandoverTask, HandoverAppAction]:
    subject = UserMirror.objects.create(
        authentik_user_id="r3-sub",
        name="r3",
        status=USER_STATUS_ACTIVE,
        dingtalk_source_slug="src",
        dingtalk_corp_id="corp",
        dingtalk_userid="r3-sub",
    )
    app = App.objects.create(
        app_key="r3-app",
        name="r3",
        handover_capability="declared",
        handover_asset_types=[
            {
                "type": "customer",
                "label": "客户",
                "detail_supported": False,
                "releasable": False,
            },
        ],
    )
    _ = AppWebhookConfig.objects.create(
        app=app,
        handover_url="https://example.test/handover",
        enabled=True,
    )
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        assignee=subject,
        assignee_state="subject",
    )
    action = HandoverAppAction.objects.create(
        task=task,
        app=app,
        status=status,
        generation=1,
        app_key_snapshot=app.app_key,
        app_name_snapshot=app.name,
    )
    _ = HandoverAssetType.objects.create(
        action=action,
        generation=1,
        type_key="customer",
        label_snapshot="客户",
        count=count,
        default_action="skip",
    )
    return subject, app, task, action


def test_async_abandon_releases_lease_on_failed_outcome() -> None:
    """LeaseHandle kwargs bug: async-abandon must not TypeError."""
    _subject, app, task, action = _subject_app_action(
        status=ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    )
    handle = take_lease(action=action, owner="async:1", batch_seq=1)
    action.status = ACTION_STATUS_ASYNC_ATTENTION_REQUIRED
    action.save(update_fields=["status", "updated_at"])
    lease = HandoverExecutionLease.objects.get(pk=handle.lease_id)
    assert lease.released_at is None

    result = async_abandon_action(
        action,
        outcome="failed",
        reason="downstream 确认不可恢复，人工失败",
        summary=None,
        actor_id="superuser-1",
    )
    assert result.status == ACTION_STATUS_FAILED
    lease.refresh_from_db()
    assert lease.released_at is not None


def test_async_abandon_done_without_summary_no_fabricated_skips() -> None:
    _subject, app, task, action = _subject_app_action(
        status=ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
        count=187,
    )
    handle = take_lease(action=action, owner="async:batch", batch_seq=1)
    batch = HandoverExecutionBatch.objects.create(
        action=action,
        action_snapshot_id=int(action.id),
        generation=1,
        batch_seq=1,
        status=BATCH_STATUS_ASYNC_PENDING,
        is_final=True,
        snapshot_token="tok",
        request_payload={},
        request_hash="0" * 64,
    )
    # 将租约绑定到 batch
    lease = HandoverExecutionLease.objects.get(pk=handle.lease_id)
    lease.action = action
    lease.batch_seq = 1
    lease.owner = f"async:{batch.pk}"
    lease.save()

    action.status = ACTION_STATUS_ASYNC_ATTENTION_REQUIRED
    action.save(update_fields=["status", "updated_at"])

    result = async_abandon_action(
        action,
        outcome="done",
        reason="已在下游人工确认完成交接",
        summary=None,
        actor_id="superuser-1",
    )
    assert result.status in {"done", ACTION_STATUS_FAILED} or result.status == "done"
    result.refresh_from_db()
    assert result.status == "done"
    # 禁止合成 skipped==count
    summary = result.result_summary or {}
    customer = summary.get("customer")
    if isinstance(customer, dict):
        assert customer.get("skipped") != 187
    else:
        assert summary.get("manual_resolution") is True
    lease.refresh_from_db()
    assert lease.released_at is not None


def test_conservation_failure_persists_failed_and_releases_lease() -> None:
    """守恒失败必须提交 failed + 释放, 不得被 atomic 回滚。"""
    _subject, app, task, action = _subject_app_action(count=10)
    handle = take_lease(action=action, owner="http:worker", batch_seq=1)
    batch = HandoverExecutionBatch.objects.create(
        action=action,
        action_snapshot_id=int(action.id),
        generation=1,
        batch_seq=1,
        status=BATCH_STATUS_EXECUTING,
        is_final=True,
        snapshot_token="tok",
        request_payload={},
        request_hash="1" * 64,
    )
    action.status = "executing"
    action.save(update_fields=["status", "updated_at"])

    bad_payload: dict[str, Any] = {
        "summary": {
            "customer": {
                "transferred": 5,
                "released": 0,
                "skipped": 0,
                "merged": 0,
                "failed": 0,
            },
        },
    }
    with pytest.raises(HandoverError, match="summary_conservation_failed"):
        complete_data_phase(batch, handle=handle, response_payload=bad_payload)

    action.refresh_from_db()
    batch.refresh_from_db()
    lease = HandoverExecutionLease.objects.get(pk=handle.lease_id)
    assert action.status == ACTION_STATUS_FAILED
    assert batch.status == BATCH_STATUS_FAILED
    assert lease.released_at is not None


def test_replayed_data_completion_does_not_merge_summary_twice() -> None:
    """Phase A 已提交后的恢复重放不得重复累计同一批 summary。"""
    _subject, _app, _task, action = _subject_app_action(count=10)
    action.status = ACTION_STATUS_EXECUTING
    action.result_summary = {
        "customer": {
            "transferred": 0,
            "released": 0,
            "skipped": 10,
            "merged": 0,
            "failed": 0,
        },
    }
    action.save(update_fields=["status", "result_summary", "updated_at"])
    handle = take_lease(action=action, owner="recovery:worker", batch_seq=1)
    batch = HandoverExecutionBatch.objects.create(
        action=action,
        action_snapshot_id=int(action.id),
        generation=1,
        batch_seq=1,
        status=BATCH_STATUS_DATA_COMPLETED,
        data_completed_at=timezone.now(),
        is_final=True,
        snapshot_token="tok",
        request_payload={},
        request_hash="2" * 64,
    )
    payload: dict[str, Any] = {
        "summary": {
            "customer": {
                "transferred": 0,
                "released": 0,
                "skipped": 10,
                "merged": 0,
                "failed": 0,
            },
        },
    }

    complete_data_phase(batch, handle=handle, response_payload=payload)

    action.refresh_from_db()
    assert action.status == ACTION_STATUS_DONE
    assert action.result_summary == payload["summary"]


def test_accepted_without_location_fails_delivery_and_releases_lease() -> None:
    _subject, _app, _task, action = _subject_app_action(count=0)
    action.status = ACTION_STATUS_EXECUTING
    action.save(update_fields=["status", "updated_at"])
    handle = take_lease(action=action, owner="sender:worker", batch_seq=1)
    batch = HandoverExecutionBatch.objects.create(
        action=action,
        action_snapshot_id=int(action.id),
        generation=1,
        batch_seq=1,
        status=BATCH_STATUS_EXECUTING,
        is_final=True,
        snapshot_token="tok",
        request_payload={},
        request_hash="3" * 64,
    )
    delivery = HandoverDeliveryAttempt.objects.create(
        batch=batch,
        delivery_seq=1,
        lease_fence=handle.fence,
        outcome=DELIVERY_OUTCOME_SENT,
    )

    with pytest.raises(HandoverError, match="状态查询 URL"):
        _handle_execute_response(
            action_id=int(action.id),
            batch_id=int(batch.id),
            delivery_id=int(delivery.id),
            handle=handle,
            response=HookResponse(status_code=202, location="", payload={"accepted": True}),
        )

    action.refresh_from_db()
    batch.refresh_from_db()
    delivery.refresh_from_db()
    lease = HandoverExecutionLease.objects.get(pk=handle.lease_id)
    assert action.status == ACTION_STATUS_FAILED
    assert batch.status == BATCH_STATUS_FAILED
    assert delivery.outcome == DELIVERY_OUTCOME_FAILED
    assert delivery.http_status == 202
    assert lease.released_at is not None


def test_later_413_keeps_partial_plan_and_releases_lease() -> None:
    _subject, _app, _task, action = _subject_app_action(count=0)
    action.status = ACTION_STATUS_EXECUTING
    action.save(update_fields=["status", "updated_at"])
    plan = HandoverBatchPlan.objects.create(
        action=action,
        action_snapshot_id=int(action.id),
        generation=1,
        total=2,
        chunks=[[], []],
        assignment_hash="4" * 64,
        status=BATCH_PLAN_STATUS_ACTIVE,
        completed_batches=1,
    )
    handle = take_lease(action=action, owner="sender:worker", batch_seq=2)
    batch = HandoverExecutionBatch.objects.create(
        action=action,
        action_snapshot_id=int(action.id),
        generation=1,
        batch_seq=2,
        status=BATCH_STATUS_EXECUTING,
        is_final=True,
        plan=plan,
        plan_batch_no=2,
        snapshot_token="tok",
        request_payload={},
        request_hash="5" * 64,
    )
    delivery = HandoverDeliveryAttempt.objects.create(
        batch=batch,
        delivery_seq=1,
        lease_fence=handle.fence,
        outcome=DELIVERY_OUTCOME_SENT,
    )

    with pytest.raises(HandoverError, match="单独指定的条目过多"):
        _handle_execute_response(
            action_id=int(action.id),
            batch_id=int(batch.id),
            delivery_id=int(delivery.id),
            handle=handle,
            response=HookResponse(status_code=413, location="", payload={}),
        )

    action.refresh_from_db()
    batch.refresh_from_db()
    plan.refresh_from_db()
    lease = HandoverExecutionLease.objects.get(pk=handle.lease_id)
    assert action.status == ACTION_STATUS_PREVIEWED
    assert action.last_error == "单独指定的条目过多，请减少逐条指定后重新预演"
    assert batch.status == BATCH_STATUS_FAILED
    assert plan.status == BATCH_PLAN_STATUS_ACTIVE
    assert plan.completed_batches == 1
    assert HandoverBatchPlan.objects.filter(action=action).count() == 1
    assert lease.released_at is not None


def test_partial_plan_rejects_grant_receiver_change() -> None:
    _subject, _app, _task, action = _subject_app_action(count=0)
    receiver = UserMirror.objects.create(
        authentik_user_id="r3-receiver",
        status=USER_STATUS_ACTIVE,
    )
    _ = HandoverBatchPlan.objects.create(
        action=action,
        action_snapshot_id=int(action.id),
        generation=1,
        total=2,
        chunks=[[], []],
        assignment_hash="6" * 64,
        status=BATCH_PLAN_STATUS_ACTIVE,
        completed_batches=1,
    )

    with pytest.raises(HandoverError, match="batch_plan_in_progress"):
        update_grant_receiver(action=action, grant_receiver=receiver)

    action.refresh_from_db()
    assert action.grant_receiver is None


def test_planned_execute_validates_grant_receiver_in_assignment_hash() -> None:
    _subject, _app, _task, action = _subject_app_action(count=0)
    receiver = UserMirror.objects.create(
        authentik_user_id="r3-hash-receiver",
        status=USER_STATUS_ACTIVE,
    )
    action.snapshot_token = "tok"
    action.save(update_fields=["snapshot_token", "updated_at"])
    _ = _ensure_batch_plan_on_413(action)
    HandoverAppAction.objects.filter(pk=action.pk).update(grant_receiver=receiver)
    action.refresh_from_db()

    with pytest.raises(HandoverError, match="batch_plan_in_progress"):
        execute_action(action, confirm_version=action.confirm_version)

    assert not HandoverExecutionBatch.objects.filter(action=action).exists()
    assert not HandoverExecutionLease.objects.filter(action=action).exists()


def test_grant_only_retry_completes_final_batch_and_plan() -> None:
    _subject, _app, _task, action = _subject_app_action(count=0)
    marker = timezone.now()
    action.status = ACTION_STATUS_FAILED
    action.data_completed_at = marker
    action.batch_seq = 1
    action.save(update_fields=["status", "data_completed_at", "batch_seq", "updated_at"])
    plan = HandoverBatchPlan.objects.create(
        action=action,
        action_snapshot_id=int(action.id),
        generation=1,
        total=1,
        chunks=[[]],
        assignment_hash="7" * 64,
        status=BATCH_PLAN_STATUS_ACTIVE,
        completed_batches=0,
    )
    batch = HandoverExecutionBatch.objects.create(
        action=action,
        action_snapshot_id=int(action.id),
        generation=1,
        batch_seq=1,
        status=BATCH_STATUS_FAILED,
        data_completed_at=marker,
        is_final=True,
        plan=plan,
        plan_batch_no=1,
        snapshot_token="tok",
        request_payload={},
        request_hash="8" * 64,
    )

    result = retry_action(action)

    batch.refresh_from_db()
    plan.refresh_from_db()
    assert result.status == ACTION_STATUS_DONE
    assert batch.status == BATCH_STATUS_DONE
    assert plan.status == BATCH_PLAN_STATUS_DONE
    assert plan.completed_batches == plan.total


def test_aggregated_summary_reads_result_summary() -> None:
    from easyauth.lifecycle.api_payloads import aggregated_summary

    _subject, app, task, action = _subject_app_action()
    action.status = "done"
    action.result_summary = {
        "customer": {
            "transferred": 185,
            "released": 1,
            "skipped": 1,
            "merged": 0,
            "failed": 0,
        },
    }
    action.save(update_fields=["status", "result_summary", "updated_at"])
    summary = aggregated_summary(action)
    assert summary is not None
    assert summary["customer"]["transferred"] == 185  # type: ignore[index]


def test_map_hook_call_error_snapshot_stale() -> None:
    from easyauth.lifecycle.api_errors import map_handover_exception
    from easyauth.webhooks.hooks import HookCallError

    mapped = map_handover_exception(HookCallError("应用交接接口返回 HTTP 412。", status_code=412))
    assert mapped is not None
    assert mapped.status_code == 412
    body = mapped.content.decode()
    assert "snapshot_stale" in body

    mapped423 = map_handover_exception(
        HookCallError("locked", status_code=423),
    )
    assert mapped423 is not None
    assert mapped423.status_code == 423
    assert "downstream_locked" in mapped423.content.decode()


def test_map_hook_call_error_413_preserves_batch_progress_details() -> None:
    from easyauth.lifecycle.api_errors import map_handover_exception
    from easyauth.webhooks.hooks import HookCallError

    mapped = map_handover_exception(
        HookCallError("too large", status_code=413),
        details={"batch_progress": {"completed": 1, "total": 3, "current_batch_seq": 2}},
    )
    assert mapped is not None
    assert mapped.status_code == 413
    import json

    body = json.loads(mapped.content.decode())
    assert body["error"]["details"]["reason"] == "payload_too_large"
    assert body["error"]["details"]["batch_progress"]["completed"] == 1


def test_attention_lease_recovery_respects_30min_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V-01: 30 分钟内 recovery beat 不得 poll / 不得烧 fence。"""
    from easyauth.lifecycle.handover import takeover_expired_lease
    from easyauth.lifecycle.models import HandoverLeaseFence
    from easyauth.tasks.lifecycle import lifecycle_recover_expired_execution_leases_task

    _subject, app, _task, action = _subject_app_action(
        status=ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    )
    action.async_status_url = "https://example.test/status/attention"
    action.save(update_fields=["async_status_url", "updated_at"])
    handle = take_lease(action=action, owner="async:seed", batch_seq=1)
    batch = HandoverExecutionBatch.objects.create(
        action=action,
        action_snapshot_id=int(action.id),
        generation=1,
        batch_seq=1,
        status=BATCH_STATUS_ASYNC_PENDING,
        is_final=True,
        snapshot_token="tok",
        request_payload={},
        request_hash="a" * 64,
    )
    lease = HandoverExecutionLease.objects.get(pk=handle.lease_id)
    now = timezone.now()
    lease.owner = f"async:{batch.pk}"
    lease.renewed_at = now - timedelta(minutes=2)
    lease.lease_expires_at = now - timedelta(seconds=30)
    lease.save(update_fields=["owner", "renewed_at", "lease_expires_at"])
    fence_before = lease.fence
    fence_row = HandoverLeaseFence.objects.get(subject_user=action.task.subject_user, app=app)
    next_fence_before = fence_row.next_fence

    get_calls = {"n": 0}

    def unexpected_get(**_kwargs: object) -> object:
        get_calls["n"] += 1
        raise AssertionError("signed_hook_get must not run within 30min attention gate")

    monkeypatch.setattr("easyauth.lifecycle.handover.signed_hook_get", unexpected_get)

    first = lifecycle_recover_expired_execution_leases_task()
    second = lifecycle_recover_expired_execution_leases_task()
    assert first["scanned"] >= 1
    assert second["scanned"] >= 1
    assert get_calls["n"] == 0

    lease.refresh_from_db()
    fence_row.refresh_from_db()
    assert lease.fence == fence_before
    assert fence_row.next_fence == next_fence_before
    # domain 入口同样跳过
    assert takeover_expired_lease(lease, owner="recover:manual") is None
    lease.refresh_from_db()
    assert lease.fence == fence_before
