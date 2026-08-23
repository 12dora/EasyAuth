"""交接异步结果的人工确认流程。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from django.db import transaction
from django.utils import timezone

from easyauth.lifecycle.core import (
    record_task_event,
    refresh_task_status_locked,
)
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.lease import (
    HANDOVER_EXECUTION_IN_FLIGHT,
    LeaseHandle,
    cas_update_owner,
    must_cas_release,
)
from easyauth.lifecycle.models import (
    ACTION_GRANT_TRANSFER_KINDS,
    ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    ACTION_STATUS_DONE,
    ACTION_STATUS_FAILED,
    BATCH_STATUS_ASYNC_PENDING,
    BATCH_STATUS_EXECUTING,
    BATCH_STATUS_FAILED,
    HandoverAppAction,
    HandoverExecutionBatch,
    HandoverExecutionLease,
    HandoverTask,
)
from easyauth.lifecycle.transfer import transfer_selected_grants

if TYPE_CHECKING:
    from easyauth.applications.ops_models import JsonValue

from easyauth.lifecycle.handover_data import (
    complete_data_phase,
)
from easyauth.lifecycle.handover_payloads import (
    audit_assignment_summary,
    audit_result_summary,
)
from easyauth.lifecycle.handover_shared import (
    ActionErrorContext,
    locked_action,
    set_action_error,
)


@dataclass(frozen=True, slots=True)
class _ManualClaim:
    locked: HandoverAppAction
    handle: LeaseHandle
    batch: HandoverExecutionBatch | None
    action_id: int
    batch_id: int | None
    app_key: str


def _validate_async_abandon_input(*, outcome: str, reason: str) -> str:
    reason_stripped = reason.strip()
    if len(reason_stripped) < 10:
        raise HandoverError("reason_required")
    if outcome not in {"done", "failed"}:
        raise HandoverError("outcome 必须为 done 或 failed")
    return reason_stripped


def _claim_async_abandon_locked(action_id: int) -> _ManualClaim:
    locked = locked_action(action_id)
    if locked.status != ACTION_STATUS_ASYNC_ATTENTION_REQUIRED:
        raise HandoverConflictError("action_not_operable")
    lease = (
        HandoverExecutionLease.objects.select_for_update()
        .filter(
            subject_user_id=locked.task.subject_user_id,
            app_id=locked.app_id,
            released_at__isnull=True,
        )
        .first()
    )
    if lease is None:
        raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
    handle = LeaseHandle(
        lease_id=int(lease.pk),  # type: ignore[arg-type]
        owner=lease.owner,
        fence=int(lease.fence),
        expires_at=lease.lease_expires_at,
    )
    if lease.owner.startswith("manual:"):
        raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
    claimed = cas_update_owner(handle, new_owner=f"manual:{uuid.uuid4().hex}", renew=True)
    if claimed is None:
        raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
    batch = (
        HandoverExecutionBatch.objects.select_for_update()
        .filter(
            action=locked,
            generation=locked.generation,
            status__in={BATCH_STATUS_ASYNC_PENDING, BATCH_STATUS_EXECUTING},
        )
        .order_by("-batch_seq")
        .first()
    )
    return _ManualClaim(
        locked=locked,
        handle=claimed,
        batch=batch,
        action_id=int(locked.id),
        batch_id=int(batch.pk) if batch is not None else None,
        app_key=locked.app.app_key,
    )


def _manual_resolution_audit_extra(
    action: HandoverAppAction,
    *,
    app_key: str,
    summary: dict[str, JsonValue] | None,
    reason: str,
    generation: int,
) -> dict[str, JsonValue]:
    return {
        "app_key": app_key,
        "manual_resolution": True,
        "summary_provided": bool(summary),
        "action_id": int(action.id),
        "generation": generation,
        "assignments": audit_assignment_summary(action),
        "summary": audit_result_summary(summary),
        "reason": reason,
    }


def _finish_async_abandon_failed(
    claim: _ManualClaim,
    *,
    reason: str,
    summary: dict[str, JsonValue] | None,
    actor_id: str,
) -> HandoverAppAction:
    locked = claim.locked
    locked.status = ACTION_STATUS_FAILED
    set_action_error(locked, reason)
    locked.async_status_url = ""
    locked.save(
        update_fields=["status", "last_error", "last_error_raw", "async_status_url", "updated_at"],
    )
    if claim.batch is not None:
        claim.batch.status = BATCH_STATUS_FAILED
        claim.batch.save(update_fields=["status"])
    must_cas_release(claim.handle)
    task = HandoverTask.objects.select_for_update().get(pk=locked.task_id)
    _ = refresh_task_status_locked(task)
    record_task_event(
        locked.task,
        action="handover_action_failed",
        actor_id=actor_id,
        actor_type="admin",
        extra=_manual_resolution_audit_extra(
            locked,
            app_key=claim.app_key,
            summary=summary,
            reason=reason,
            generation=locked.generation,
        ),
    )
    return locked


def _transfer_grants_without_batch(claim: _ManualClaim) -> None:
    locked = claim.locked
    if locked.task.kind not in ACTION_GRANT_TRANSFER_KINDS:
        return
    try:
        _ = transfer_selected_grants(locked)
    except Exception as error:
        locked.status = ACTION_STATUS_FAILED
        set_action_error(
            locked,
            error,
            ActionErrorContext(stable_message="授权转移失败"),
        )
        locked.save(
            update_fields=["status", "last_error", "last_error_raw", "updated_at"],
        )
        must_cas_release(claim.handle)
        raise HandoverError("授权转移失败") from error


def _finish_async_abandon_done_without_batch(
    claim: _ManualClaim,
    *,
    reason: str,
    summary: dict[str, JsonValue] | None,
    actor_id: str,
) -> HandoverAppAction:
    locked = claim.locked
    locked.status = ACTION_STATUS_DONE
    locked.async_status_url = ""
    locked.last_error = ""
    locked.result_summary = summary if summary else None
    locked.data_completed_at = locked.data_completed_at or timezone.now()
    locked.save(
        update_fields=[
            "status",
            "async_status_url",
            "last_error",
            "result_summary",
            "data_completed_at",
            "updated_at",
        ],
    )
    _transfer_grants_without_batch(claim)
    must_cas_release(claim.handle)
    task = HandoverTask.objects.select_for_update().get(pk=locked.task_id)
    _ = refresh_task_status_locked(task)
    record_task_event(
        locked.task,
        action="handover_action_executed",
        actor_id=actor_id,
        actor_type="admin",
        extra=_manual_resolution_audit_extra(
            locked,
            app_key=claim.app_key,
            summary=summary,
            reason=reason,
            generation=locked.generation,
        ),
    )
    return locked


def async_abandon_action(
    action: HandoverAppAction,
    *,
    outcome: str,
    reason: str,
    summary: dict[str, JsonValue] | None,
    actor_id: str,
) -> HandoverAppAction:
    """§6.3 async-abandon: 超管人工确认异步结局, 同一次 fence CAS 释放租约。"""
    reason_stripped = _validate_async_abandon_input(outcome=outcome, reason=reason)

    # 解析租约与 batch(短事务)
    with transaction.atomic():
        claim = _claim_async_abandon_locked(action.id)
        if outcome == "failed":
            return _finish_async_abandon_failed(
                claim,
                reason=reason_stripped,
                summary=summary,
                actor_id=actor_id,
            )
        # done 且无 batch: 直接结案(不伪造 summary)
        if claim.batch is None:
            return _finish_async_abandon_done_without_batch(
                claim,
                reason=reason_stripped,
                summary=summary,
                actor_id=actor_id,
            )

        # done + 有 batch: 保持人工 owner/fence, 退出本事务后走 complete_data_phase。
        # is_final 是批次计划事实, 人工确认不得篡改。

    # 人工结案: 有 summary 则落库; 无则不伪造 skipped==count
    payload: dict[str, JsonValue] | None
    if summary:
        payload = {"summary": cast("JsonValue", summary)}
    else:
        payload = None
    assert claim.batch_id is not None
    complete_data_phase(
        HandoverExecutionBatch.objects.get(pk=claim.batch_id),
        handle=claim.handle,
        response_payload=payload,
        enforce_conservation=False,
        summary_unknown=not bool(summary),
        audit_actor_id=actor_id,
        audit_actor_type="admin",
        audit_extra={
            **_manual_resolution_audit_extra(
                action,
                app_key=claim.app_key,
                summary=summary,
                reason=reason_stripped,
                generation=action.generation,
            ),
        },
    )
    locked = HandoverAppAction.objects.select_related("app", "task").get(pk=claim.action_id)
    return locked
