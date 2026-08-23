"""交接执行批次的预留与事务外投递编排。"""

from __future__ import annotations

import hashlib
import json
import uuid

from django.db import transaction

from easyauth.lifecycle.core import (
    ACTION_NOT_OPERABLE_MESSAGE,
    HOOK_EVENT_EXECUTE,
    LIFECYCLE_ACTOR_ID,
    ensure_action_status,
    record_task_event,
    refresh_task_status_locked,
)
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover_delivery import (
    DeliveryFailureSpec,
    finish_delivery_failure,
    handle_execute_response,
)
from easyauth.lifecycle.handover_payloads import (
    active_batch_plan,
    build_execute_payload_for_plan,
    complete_active_plan,
)
from easyauth.lifecycle.handover_shared import (
    DECLARED_WITHOUT_URL_MESSAGE,
    ExecuteRequestBody,
    GrantOnlyRetryOutcome,
    MutationGuard,
    OutboundExecution,
    handover_hook_url,
    locked_action,
    set_action_error,
)
from easyauth.lifecycle.handover_validation import (
    validate_assignments,
)
from easyauth.lifecycle.lease import (
    HANDOVER_EXECUTION_IN_FLIGHT,
    LeaseHandle,
    cas_release,
    cas_update_owner,
    must_cas_release,
    require_cas,
    take_lease,
)
from easyauth.lifecycle.models import (
    ACTION_GRANT_TRANSFER_KINDS,
    ACTION_STATUS_DONE,
    ACTION_STATUS_EXECUTING,
    ACTION_STATUS_FAILED,
    BATCH_STATUS_DONE,
    BATCH_STATUS_EXECUTING,
    BATCH_STATUS_FAILED,
    DELIVERY_OUTCOME_SENT,
    DELIVERY_OUTCOME_SUPERSEDED,
    HandoverAppAction,
    HandoverDeliveryAttempt,
    HandoverExecutionBatch,
    HandoverTask,
)
from easyauth.lifecycle.transfer import transfer_selected_grants
from easyauth.webhooks.hooks import HookCallError, signed_hook_post


def assert_action_executable(
    action: HandoverAppAction,
    *,
    allowed_status: str,
    confirm_version: int | None,
    is_retry: bool,
    mutation_guard: MutationGuard | None,
) -> None:
    if mutation_guard is not None:
        mutation_guard(action)
    if is_retry and action.status != ACTION_STATUS_FAILED:
        # 01 §6.1: 对非 failed 调 retry → action_not_retryable(非泛化 action_not_operable)
        raise HandoverConflictError("action_not_retryable")
    ensure_action_status(action, allowed={allowed_status})
    if confirm_version is not None and confirm_version != action.confirm_version:
        raise HandoverConflictError("confirm_version_stale")
    validate_assignments(action)


def retry_grant_transfer_only(
    action: HandoverAppAction,
    *,
    worker_owner: str,
) -> GrantOnlyRetryOutcome:
    handle = take_lease(
        action=action,
        owner=worker_owner,
        batch_seq=action.batch_seq or 1,
    )
    action.status = ACTION_STATUS_EXECUTING
    action.attempts += 1
    action.save(update_fields=["status", "attempts", "updated_at"])
    action_id_grant = action.id
    try:
        require_cas(handle)
        if action.task.kind in ACTION_GRANT_TRANSFER_KINDS:
            _ = transfer_selected_grants(action)
        final_batch = (
            HandoverExecutionBatch.objects.select_for_update()
            .filter(
                action=action,
                generation=action.generation,
                is_final=True,
                data_completed_at__isnull=False,
            )
            .order_by("-batch_seq")
            .first()
        )
        if final_batch is None:
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        final_batch.status = BATCH_STATUS_DONE
        final_batch.save(update_fields=["status"])
        complete_active_plan(action)
        action.status = ACTION_STATUS_DONE
        action.last_error = ""
        action.snapshot_token = ""
        action.save(
            update_fields=["status", "last_error", "snapshot_token", "updated_at"],
        )
        task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
        _ = refresh_task_status_locked(task)
        must_cas_release(handle)
    except Exception as error:
        action = HandoverAppAction.objects.select_for_update(of=("self",)).get(
            pk=action_id_grant,
        )
        action.status = ACTION_STATUS_FAILED
        set_action_error(action, error)
        action.save(
            update_fields=["status", "last_error", "last_error_raw", "updated_at"],
        )
        _ = cas_release(handle)
        return GrantOnlyRetryOutcome(error=error)
    return GrantOnlyRetryOutcome(done_id=action_id_grant)


def settle_grant_only_retry(outcome: GrantOnlyRetryOutcome) -> HandoverAppAction:
    if outcome.error is not None:
        raise HandoverError(str(outcome.error)[:500]) from outcome.error
    assert outcome.done_id is not None
    return HandoverAppAction.objects.get(pk=outcome.done_id)


def open_execution_batch(
    action: HandoverAppAction,
    *,
    worker_owner: str,
    is_retry: bool,
) -> OutboundExecution:
    hook_url = handover_hook_url(action.app)
    if not hook_url:
        raise HandoverError(DECLARED_WITHOUT_URL_MESSAGE)

    plan = active_batch_plan(action)
    payload, is_final, plan_batch_no = build_execute_payload_for_plan(action, plan)
    payload_bytes = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    request_body = ExecuteRequestBody(
        payload=payload,
        request_hash=hashlib.sha256(payload_bytes).hexdigest(),
        is_final=is_final,
        plan=plan,
        plan_batch_no=plan_batch_no,
    )

    if is_retry:
        handle, batch, delivery = _reopen_failed_batch(action, worker_owner=worker_owner)
    else:
        handle, batch, delivery = _start_execution_batch(
            action,
            worker_owner=worker_owner,
            request_body=request_body,
        )

    handle = _hand_lease_to_sender(handle, delivery=delivery, worker_owner=worker_owner)
    return OutboundExecution(
        action_id=action.id,
        batch_id=batch.id,
        delivery_id=delivery.id,
        handle=handle,
        app=action.app,
        url=hook_url,
        body=dict(batch.request_payload),
    )


def _reopen_failed_batch(
    action: HandoverAppAction,
    *,
    worker_owner: str,
) -> tuple[LeaseHandle, HandoverExecutionBatch, HandoverDeliveryAttempt]:
    batch = (
        HandoverExecutionBatch.objects.select_for_update()
        .filter(
            action=action,
            generation=action.generation,
            status=BATCH_STATUS_FAILED,
        )
        .order_by("-batch_seq")
        .first()
    )
    if batch is None:
        raise HandoverConflictError("action_not_retryable")
    # 失败重试必须用原 canonical body, 不得改写 request_payload。
    handle = take_lease(
        action=action,
        owner=worker_owner,
        batch_seq=batch.batch_seq,
    )
    batch.status = BATCH_STATUS_EXECUTING
    batch.save(update_fields=["status"])
    next_seq = HandoverDeliveryAttempt.objects.filter(batch=batch).count() + 1
    delivery = HandoverDeliveryAttempt.objects.create(
        batch=batch,
        delivery_seq=next_seq,
        lease_fence=handle.fence,
        outcome=DELIVERY_OUTCOME_SENT,
    )
    return handle, batch, delivery


def _start_execution_batch(
    action: HandoverAppAction,
    *,
    worker_owner: str,
    request_body: ExecuteRequestBody,
) -> tuple[LeaseHandle, HandoverExecutionBatch, HandoverDeliveryAttempt]:
    next_batch_seq = action.batch_seq + 1
    handle = take_lease(
        action=action,
        owner=worker_owner,
        batch_seq=next_batch_seq,
    )
    action.batch_seq = next_batch_seq
    action.status = ACTION_STATUS_EXECUTING
    action.attempts += 1
    action.last_error = ""
    action.save(
        update_fields=[
            "batch_seq",
            "status",
            "attempts",
            "last_error",
            "updated_at",
        ],
    )
    batch = HandoverExecutionBatch.objects.create(
        action=action,
        action_snapshot_id=int(action.id),
        generation=action.generation,
        batch_seq=next_batch_seq,
        is_final=request_body.is_final,
        plan=request_body.plan,
        plan_batch_no=request_body.plan_batch_no,
        snapshot_token=action.snapshot_token,
        request_payload=request_body.payload,
        request_hash=request_body.request_hash,
        status=BATCH_STATUS_EXECUTING,
        task_snapshot={
            "task_id": action.task_id,
            "kind": action.task.kind,
            "app_key": action.app.app_key,
            "subject_user_id": action.task.subject_user.authentik_user_id,
        },
    )
    delivery = HandoverDeliveryAttempt.objects.create(
        batch=batch,
        delivery_seq=1,
        lease_fence=handle.fence,
        outcome=DELIVERY_OUTCOME_SENT,
    )
    return handle, batch, delivery


def _hand_lease_to_sender(
    handle: LeaseHandle,
    *,
    delivery: HandoverDeliveryAttempt,
    worker_owner: str,
) -> LeaseHandle:
    delivery_owner = f"delivery:{delivery.pk}"
    handed = cas_update_owner(handle, new_owner=delivery_owner, renew=True)
    if handed is None:
        raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
    sender_owner = f"sender:{worker_owner}"
    claimed = cas_update_owner(handed, new_owner=sender_owner, renew=True)
    if claimed is None:
        raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
    return claimed


def deliver_execute_request(outbound: OutboundExecution) -> HandoverAppAction:
    # 网络调用在事务外
    if _release_superseded_delivery(outbound):
        raise HandoverConflictError("generation_superseded")
    try:
        response = signed_hook_post(
            app=outbound.app,
            url=outbound.url,
            event_type=HOOK_EVENT_EXECUTE,
            delivery_id=uuid.uuid4().hex,
            payload=outbound.body,
        )
    except HookCallError as error:
        finish_delivery_failure(
            DeliveryFailureSpec(
                outbound.action_id,
                outbound.batch_id,
                outbound.delivery_id,
                outbound.handle,
                error=error,
                http_status=error.status_code,
                response_payload=error.payload,
                raw_body=error.raw_body,
                retry_after_seconds=error.retry_after_seconds,
            ),
        )
        raise

    return handle_execute_response(
        action_id=outbound.action_id,
        batch_id=outbound.batch_id,
        delivery_id=outbound.delivery_id,
        handle=outbound.handle,
        response=response,
    )


def _release_superseded_delivery(outbound: OutboundExecution) -> bool:
    """代次已被推进时把该次投递标记 superseded 并释放租约。"""
    superseded = False
    with transaction.atomic():
        action = locked_action(outbound.action_id)
        batch = HandoverExecutionBatch.objects.select_for_update().get(pk=outbound.batch_id)
        if batch.generation != action.generation or batch.generation != action.task.generation:
            delivery = HandoverDeliveryAttempt.objects.select_for_update().get(
                pk=outbound.delivery_id,
            )
            delivery.outcome = DELIVERY_OUTCOME_SUPERSEDED
            delivery.error_text = "generation_superseded"
            delivery.save(update_fields=["outcome", "error_text"])
            batch.status = BATCH_STATUS_FAILED
            batch.save(update_fields=["status"])
            must_cas_release(outbound.handle)
            superseded = True
            record_task_event(
                action.task,
                action="handover_delivery_superseded",
                actor_id=LIFECYCLE_ACTOR_ID,
                actor_type="system",
                extra={"app_key": action.app_key_snapshot, "batch_id": outbound.batch_id},
            )
    return superseded
