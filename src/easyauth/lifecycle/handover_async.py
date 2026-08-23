"""交接异步执行的租约认领、轮询与回写。"""

from __future__ import annotations

import uuid
from datetime import timedelta
from http import HTTPStatus

from django.db import transaction
from django.utils import timezone

from easyauth.lifecycle.core import (
    ACTION_NOT_OPERABLE_MESSAGE,
    ASYNC_ACCEPTED_LOCATION_REQUIRED_MESSAGE,
    ASYNC_ATTENTION_POLL_INTERVAL_SECONDS,
    ASYNC_POLL_LIMIT_MESSAGE,
    ASYNC_POLL_MAX_ATTEMPTS,
    ASYNC_STATUS_URL_REQUIRED_MESSAGE,
    HOOK_EVENT_EXECUTE,
    LIFECYCLE_ACTOR_ID,
    ensure_action_status,
    record_task_event,
)
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover_data import (
    CompleteDataPhaseSpec,
    complete_data_phase,
)
from easyauth.lifecycle.handover_shared import (
    AsyncPollClaim,
    locked_action,
    logger,
    set_action_error,
)
from easyauth.lifecycle.lease import (
    HANDOVER_EXECUTION_IN_FLIGHT,
    LeaseHandle,
    cas_update_owner,
    require_cas,
)
from easyauth.lifecycle.models import (
    ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    ACTION_STATUS_ASYNC_PENDING,
    HandoverAppAction,
    HandoverExecutionBatch,
    HandoverExecutionLease,
)
from easyauth.webhooks.hooks import HookCallError, HookResponse, signed_hook_get


def _claim_async_poll_lease(
    lease: HandoverExecutionLease,
    *,
    poller: str,
    sentinel_owner: str,
) -> LeaseHandle:
    """从 async sentinel claim; 已被其他 poller 持有或属主异常均判在途冲突。"""
    handle = LeaseHandle(
        lease_id=int(lease.pk),  # type: ignore[arg-type]
        owner=lease.owner,
        fence=int(lease.fence),
        expires_at=lease.lease_expires_at,
    )
    if lease.owner.startswith("async:") or lease.owner == sentinel_owner:
        claimed = cas_update_owner(handle, new_owner=poller, renew=True)
        if claimed is None:
            raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
        return claimed
    if lease.owner.startswith("poller:"):
        # 已被其他 poller 持有
        if lease.owner != poller:
            raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
        return handle
    raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)


def _exhaust_async_poll_attempts(
    action: HandoverAppAction,
    *,
    handle: LeaseHandle,
    batch: HandoverExecutionBatch,
) -> None:
    action.status = ACTION_STATUS_ASYNC_ATTENTION_REQUIRED
    action.save(update_fields=["status", "updated_at"])
    # 移回 sentinel 并续租, 不释放
    _ = cas_update_owner(handle, new_owner=f"async:{batch.pk}", renew=True)
    logger.warning(
        "async poll limit reached: action_id=%s app=%s attempts=%s",
        action.id,
        action.app_key_snapshot,
        action.async_poll_attempts,
    )
    record_task_event(
        action.task,
        action="handover_async_attention_required",
        actor_id=LIFECYCLE_ACTOR_ID,
        actor_type="system",
        extra={
            "app_key": action.app_key_snapshot,
            "async_poll_attempts": action.async_poll_attempts,
            "message": ASYNC_POLL_LIMIT_MESSAGE,
        },
    )


def _open_async_poll(
    action: HandoverAppAction,
    *,
    poller: str,
) -> tuple[HandoverAppAction, AsyncPollClaim | None]:
    """事务 A: 校验状态、claim 租约并记账轮询次数。claim 为 None 表示本轮不发网。"""
    with transaction.atomic():
        action = locked_action(action.id)
        ensure_action_status(
            action,
            allowed={ACTION_STATUS_ASYNC_PENDING, ACTION_STATUS_ASYNC_ATTENTION_REQUIRED},
        )
        if not action.async_status_url:
            raise HandoverConflictError(ASYNC_STATUS_URL_REQUIRED_MESSAGE)
        lease = (
            HandoverExecutionLease.objects.select_for_update()
            .filter(
                action=action,
                generation=action.generation,
                released_at__isnull=True,
            )
            .first()
        )
        if lease is None:
            raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
        if action.status == ACTION_STATUS_ASYNC_ATTENTION_REQUIRED:
            cutoff = timezone.now() - timedelta(
                seconds=ASYNC_ATTENTION_POLL_INTERVAL_SECONDS,
            )
            if action.updated_at > cutoff:
                return action, None
        batch = (
            HandoverExecutionBatch.objects.filter(
                action=action,
                generation=action.generation,
                batch_seq=lease.batch_seq,
            )
            .order_by("-id")
            .first()
        )
        if batch is None:
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        handle = _claim_async_poll_lease(
            lease,
            poller=poller,
            sentinel_owner=f"async:{batch.pk}",
        )

        if action.status == ACTION_STATUS_ASYNC_ATTENTION_REQUIRED:
            # updated_at 在 attention 状态下作为权威 last_polled_at; claim 后、发网前落库,
            # worker 随后崩溃也不会让 recovery 在 30 分钟内重复 GET。
            action.save(update_fields=["updated_at"])

        if action.status == ACTION_STATUS_ASYNC_PENDING:
            if action.async_poll_attempts >= ASYNC_POLL_MAX_ATTEMPTS:
                _exhaust_async_poll_attempts(action, handle=handle, batch=batch)
                return action, None
            action.async_poll_attempts += 1
            action.save(update_fields=["async_poll_attempts", "updated_at"])
    return action, AsyncPollClaim(batch=batch, handle=handle)


def _record_async_poll_failure(
    action_id: int,
    *,
    error: Exception,
    claim: AsyncPollClaim,
) -> None:
    with transaction.atomic():
        action = locked_action(action_id)
        if action.status in {
            ACTION_STATUS_ASYNC_PENDING,
            ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
        }:
            set_action_error(action, error)
            action.save(update_fields=["last_error", "last_error_raw", "updated_at"])
        # 移回 sentinel
        _handoff_to_async_sentinel(action, claim.handle, batch_id=claim.batch.pk)


def _accept_async_poll_progress(
    action_id: int,
    *,
    response: HookResponse,
    claim: AsyncPollClaim,
) -> HandoverAppAction:
    with transaction.atomic():
        action = locked_action(action_id)
        require_cas(claim.handle)
        if action.status not in {
            ACTION_STATUS_ASYNC_PENDING,
            ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
        }:
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        action.async_status_url = response.location
        action.last_error = ""
        action.save(update_fields=["async_status_url", "last_error", "updated_at"])
        _handoff_to_async_sentinel(action, claim.handle, batch_id=claim.batch.pk)
    return action


def poll_async_action(
    action: HandoverAppAction, *, worker_id: str | None = None
) -> HandoverAppAction:
    """异步轮询: claim → GET → 终态走 complete_data_phase; 超次数 → async_attention_required。"""
    poller = worker_id or f"poller:{uuid.uuid4().hex[:12]}"
    action, claim = _open_async_poll(action, poller=poller)
    if claim is None:
        return action

    try:
        response = signed_hook_get(
            app=action.app,
            url=action.async_status_url,
            event_type=HOOK_EVENT_EXECUTE,
            delivery_id=uuid.uuid4().hex,
        )
        _validate_poll_response(response)
    except (HookCallError, HandoverError) as error:
        _record_async_poll_failure(action.id, error=error, claim=claim)
        raise

    if response.status_code == HTTPStatus.ACCEPTED:
        return _accept_async_poll_progress(action.id, response=response, claim=claim)

    # 终态 200: complete_data_phase 自管 A/B/C 事务, 调用方不得再包 atomic。
    complete_data_phase(
        HandoverExecutionBatch.objects.get(pk=claim.batch.pk),
        CompleteDataPhaseSpec(
            handle=claim.handle,
            response_payload=response.payload,
        ),
    )
    action = HandoverAppAction.objects.get(pk=action.id)
    record_task_event(
        action.task,
        action="handover_action_executed",
        actor_id=LIFECYCLE_ACTOR_ID,
        actor_type="system",
        extra={"app_key": action.app_key_snapshot, "via": "async_poll"},
    )
    return action


def _ensure_accepted_location(response: HookResponse, *, message: str) -> None:
    if not response.location:
        raise HandoverError(message)


def _validate_poll_response(response: HookResponse) -> None:
    if response.status_code not in {HTTPStatus.OK, HTTPStatus.ACCEPTED}:
        message = f"应用交接状态接口返回不支持的成功状态 {response.status_code}。"
        raise HookCallError(
            message,
            status_code=response.status_code,
            payload=response.payload,
            raw_body=response.raw_body,
            location=response.location,
        )
    if response.status_code == HTTPStatus.ACCEPTED:
        _ensure_accepted_location(
            response,
            message=ASYNC_ACCEPTED_LOCATION_REQUIRED_MESSAGE,
        )


def _handoff_to_async_sentinel(
    action: HandoverAppAction,
    handle: LeaseHandle,
    *,
    batch_id: int,
) -> None:
    _ = action
    handed = cas_update_owner(handle, new_owner=f"async:{batch_id}", renew=True)
    if handed is None:
        raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
