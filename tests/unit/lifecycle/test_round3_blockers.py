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
    async_abandon_action,
    complete_data_phase,
    validate_execute_summary_conservation,
)
from easyauth.lifecycle.lease import LeaseHandle, take_lease
from easyauth.lifecycle.models import (
    ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    ACTION_STATUS_FAILED,
    ACTION_STATUS_PREVIEWED,
    BATCH_STATUS_ASYNC_PENDING,
    BATCH_STATUS_EXECUTING,
    BATCH_STATUS_FAILED,
    HANDOVER_KIND_OFFBOARD,
    HandoverAppAction,
    HandoverAssetType,
    HandoverExecutionBatch,
    HandoverExecutionLease,
    HandoverTask,
)
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
