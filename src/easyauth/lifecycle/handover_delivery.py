"""交接执行响应分支与失败落库。"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

from django.db import transaction

from easyauth.lifecycle.core import (
    EXECUTE_ACCEPTED_LOCATION_REQUIRED_MESSAGE,
    LIFECYCLE_ACTOR_ID,
    record_task_event,
    refresh_task_status_locked,
)
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.lease import (
    HANDOVER_EXECUTION_IN_FLIGHT,
    LeaseHandle,
    cas_update_owner,
    must_cas_release,
    require_cas,
)
from easyauth.lifecycle.models import (
    ACTION_STATUS_ASYNC_PENDING,
    ACTION_STATUS_FAILED,
    ACTION_STATUS_PENDING,
    ACTION_STATUS_PREVIEWED,
    BATCH_STATUS_ASYNC_PENDING,
    BATCH_STATUS_FAILED,
    BATCH_STATUS_PENDING,
    DELIVERY_OUTCOME_ASYNC_ACCEPTED,
    DELIVERY_OUTCOME_FAILED,
    DELIVERY_OUTCOME_SUCCEEDED,
    HandoverAppAction,
    HandoverDeliveryAttempt,
    HandoverExecutionBatch,
    HandoverTask,
)
from easyauth.outbox.services import enqueue_task

if TYPE_CHECKING:
    from easyauth.applications.ops_models import JsonValue
    from easyauth.webhooks.hooks import HookResponse

from easyauth.lifecycle.handover_data import (
    complete_data_phase,
)
from easyauth.lifecycle.handover_payloads import (
    active_batch_plan,
    ensure_batch_plan_on_413,
)
from easyauth.lifecycle.handover_shared import (
    DEFAULT_RETRY_AFTER_SECONDS,
    RATE_LIMITED_EXECUTE_RETRY_TASK,
    UNSHARDABLE_BATCH_MESSAGE,
    ActionErrorContext,
    error_response_evidence,
    locked_action,
    redact_error_text,
    redact_response_payload,
    set_action_error,
)


def handle_execute_response(
    *,
    action_id: int,
    batch_id: int,
    delivery_id: int,
    handle: LeaseHandle,
    response: HookResponse,
) -> HandoverAppAction:
    status = response.status_code
    if status == HTTPStatus.ACCEPTED:
        if not response.location:
            error = HandoverError(EXECUTE_ACCEPTED_LOCATION_REQUIRED_MESSAGE)
            finish_delivery_failure(
                DeliveryFailureSpec(
                    action_id,
                    batch_id,
                    delivery_id,
                    handle,
                    error=error,
                    http_status=status,
                    response_payload=response.payload,
                    raw_body=response.raw_body,
                ),
            )
            raise error
        return _accept_execute_response(
            action_id=action_id,
            batch_id=batch_id,
            delivery_id=delivery_id,
            handle=handle,
            response=response,
        )

    if status == HTTPStatus.OK:
        return _complete_execute_response(
            action_id=action_id,
            batch_id=batch_id,
            delivery_id=delivery_id,
            handle=handle,
            response=response,
        )

    # 412 / 413 / 423 / 429 / 4xx / 5xx
    finish_delivery_failure(
        DeliveryFailureSpec(
            action_id,
            batch_id,
            delivery_id,
            handle,
            error=HandoverError(f"execute HTTP {status}"),
            http_status=status,
            response_payload=response.payload,
            raw_body=response.raw_body,
        ),
    )
    action = HandoverAppAction.objects.get(pk=action_id)
    raise HandoverError(action.last_error or f"execute HTTP {status}")


def _accept_execute_response(
    *,
    action_id: int,
    batch_id: int,
    delivery_id: int,
    handle: LeaseHandle,
    response: HookResponse,
) -> HandoverAppAction:
    with transaction.atomic():
        require_cas(handle)
        action = locked_action(action_id)
        batch = HandoverExecutionBatch.objects.select_for_update().get(pk=batch_id)
        delivery = HandoverDeliveryAttempt.objects.select_for_update().get(pk=delivery_id)
        delivery.outcome = DELIVERY_OUTCOME_ASYNC_ACCEPTED
        delivery.http_status = response.status_code
        delivery.response_payload = redact_response_payload(response.payload)
        delivery.save(update_fields=["outcome", "http_status", "response_payload"])
        batch.status = BATCH_STATUS_ASYNC_PENDING
        batch.save(update_fields=["status"])
        action.status = ACTION_STATUS_ASYNC_PENDING
        action.async_status_url = response.location
        action.last_error = ""
        action.save(update_fields=["status", "async_status_url", "last_error", "updated_at"])
        # 202 不释放, 移交 async sentinel
        handed = cas_update_owner(handle, new_owner=f"async:{batch.pk}", renew=True)
        if handed is None:
            raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
        task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
        _ = refresh_task_status_locked(task)
    return action


def _complete_execute_response(
    *,
    action_id: int,
    batch_id: int,
    delivery_id: int,
    handle: LeaseHandle,
    response: HookResponse,
) -> HandoverAppAction:
    # delivery 成功标记与 complete_data_phase 分离, 避免 A/B/C 被外层 atomic 回滚。
    with transaction.atomic():
        require_cas(handle)
        delivery = HandoverDeliveryAttempt.objects.select_for_update().get(pk=delivery_id)
        delivery.outcome = DELIVERY_OUTCOME_SUCCEEDED
        delivery.http_status = response.status_code
        delivery.response_payload = redact_response_payload(response.payload)
        delivery.save(update_fields=["outcome", "http_status", "response_payload"])
    complete_data_phase(
        HandoverExecutionBatch.objects.get(pk=batch_id),
        handle=handle,
        response_payload=response.payload,
    )
    action = HandoverAppAction.objects.get(pk=action_id)
    record_task_event(
        action.task,
        action="handover_action_executed",
        actor_id=LIFECYCLE_ACTOR_ID,
        actor_type="system",
        extra={"app_key": action.app.app_key},
    )
    return action


@dataclass(frozen=True, slots=True)
class DeliveryFailureSpec:
    action_id: int
    batch_id: int
    delivery_id: int
    handle: LeaseHandle
    error: Exception
    http_status: int | None
    response_payload: dict[str, JsonValue] | None = None
    raw_body: str = ""
    retry_after_seconds: int | None = None


def _record_delivery_failure_evidence(
    delivery: HandoverDeliveryAttempt,
    failure: DeliveryFailureSpec,
) -> None:
    delivery.outcome = DELIVERY_OUTCOME_FAILED
    delivery.http_status = failure.http_status
    delivery.error_text = redact_error_text(str(failure.error))
    delivery.response_payload = error_response_evidence(
        failure.response_payload,
        raw_body=failure.raw_body,
    )
    delivery.save(update_fields=["outcome", "http_status", "error_text", "response_payload"])


def _schedule_rate_limited_execute_retry(
    delivery: HandoverDeliveryAttempt,
    action: HandoverAppAction,
    retry_after_seconds: int | None,
) -> None:
    delay = retry_after_seconds or DEFAULT_RETRY_AFTER_SECONDS
    enqueue_task(
        event_key=f"handover-rate-limited-execute:{delivery.id}",
        task_name=RATE_LIMITED_EXECUTE_RETRY_TASK,
        args=[action.id, action.generation],
        countdown=delay,
    )


def _apply_recoverable_delivery_failure(
    action: HandoverAppAction,
    batch: HandoverExecutionBatch,
    delivery: HandoverDeliveryAttempt,
    failure: DeliveryFailureSpec,
) -> bool:
    if failure.http_status not in {
        HTTPStatus.PRECONDITION_FAILED,
        HTTPStatus.LOCKED,
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    }:
        return False
    stable_message: str | None = None
    error = failure.error
    if failure.http_status == HTTPStatus.TOO_MANY_REQUESTS:
        batch.status = BATCH_STATUS_PENDING
        action.status = ACTION_STATUS_PREVIEWED
    elif failure.http_status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE:
        batch.status = BATCH_STATUS_FAILED
        action.status = ACTION_STATUS_PREVIEWED
        action.snapshot_token = ""
        plan = active_batch_plan(action)
        if plan is not None and plan.completed_batches > 0:
            error = HandoverError(UNSHARDABLE_BATCH_MESSAGE)
            stable_message = str(error)
        else:
            _ = ensure_batch_plan_on_413(action)
    else:
        batch.status = BATCH_STATUS_FAILED
        action.status = ACTION_STATUS_PENDING
        action.snapshot_token = ""
    set_action_error(
        action,
        error,
        ActionErrorContext(
            status_code=None if stable_message is not None else failure.http_status,
            payload=failure.response_payload,
            raw_body=failure.raw_body,
            stable_message=stable_message,
        ),
    )
    action.save(
        update_fields=["status", "snapshot_token", "last_error", "last_error_raw", "updated_at"],
    )
    batch.save(update_fields=["status"])
    if failure.http_status == HTTPStatus.TOO_MANY_REQUESTS:
        _schedule_rate_limited_execute_retry(delivery, action, failure.retry_after_seconds)
    must_cas_release(failure.handle)
    return True


def _apply_terminal_delivery_failure(
    action: HandoverAppAction,
    batch: HandoverExecutionBatch,
    failure: DeliveryFailureSpec,
) -> None:
    batch.status = BATCH_STATUS_FAILED
    batch.save(update_fields=["status"])
    action.status = ACTION_STATUS_FAILED
    set_action_error(
        action,
        failure.error,
        ActionErrorContext(
            status_code=failure.http_status,
            payload=failure.response_payload,
            raw_body=failure.raw_body,
        ),
    )
    action.save(update_fields=["status", "last_error", "last_error_raw", "updated_at"])
    must_cas_release(failure.handle)
    task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
    _ = refresh_task_status_locked(task)


def _record_delivery_failure_event(action: HandoverAppAction) -> None:
    record_task_event(
        action.task,
        action="handover_action_failed",
        actor_id=LIFECYCLE_ACTOR_ID,
        actor_type="system",
        extra={"app_key": action.app.app_key, "error": action.last_error},
    )


def finish_delivery_failure(failure: DeliveryFailureSpec) -> None:
    with transaction.atomic():
        require_cas(failure.handle)
        action = locked_action(failure.action_id)
        batch = HandoverExecutionBatch.objects.select_for_update().get(pk=failure.batch_id)
        delivery = HandoverDeliveryAttempt.objects.select_for_update().get(pk=failure.delivery_id)
        _record_delivery_failure_evidence(delivery, failure)
        if _apply_recoverable_delivery_failure(action, batch, delivery, failure):
            return
        _apply_terminal_delivery_failure(action, batch, failure)
    _record_delivery_failure_event(action)
