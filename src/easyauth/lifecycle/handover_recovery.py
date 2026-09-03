"""交接过期执行租约的接管与恢复。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from http import HTTPStatus

from django.db import transaction
from django.utils import timezone

from easyauth.applications.models import HANDOVER_CAPABILITY_DECLARED, App
from easyauth.lifecycle.core import (
    ASYNC_ATTENTION_POLL_INTERVAL_SECONDS,
    HOOK_EVENT_EXECUTE,
    LIFECYCLE_ACTOR_ID,
    record_task_event,
    refresh_task_status_locked,
)
from easyauth.lifecycle.errors import HandoverConflictError
from easyauth.lifecycle.handover_async import (
    poll_async_action,
)
from easyauth.lifecycle.handover_delivery import (
    handle_execute_response,
)
from easyauth.lifecycle.handover_shared import (
    ActionErrorContext,
    handover_hook_url,
    locked_action,
    logger,
    redact_response_payload,
    set_action_error,
)
from easyauth.lifecycle.lease import (
    HANDOVER_EXECUTION_IN_FLIGHT,
    LeaseHandle,
    cas_release,
    cas_update_owner,
    preempt_expired_lease,
    require_cas,
)
from easyauth.lifecycle.models import (
    ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    ACTION_STATUS_ASYNC_PENDING,
    ACTION_STATUS_BLOCKED,
    BATCH_STATUS_FAILED,
    BLOCKED_REASON_CAPABILITY_UNDECLARED,
    DELIVERY_OUTCOME_FAILED,
    DELIVERY_OUTCOME_SENT,
    HandoverAppAction,
    HandoverDeliveryAttempt,
    HandoverExecutionBatch,
    HandoverExecutionLease,
    HandoverTask,
)
from easyauth.webhooks.hooks import HookCallError, HookResponse, signed_hook_post


@dataclass(frozen=True, slots=True)
class _TakeoverDelivery:
    action: HandoverAppAction
    batch: HandoverExecutionBatch
    delivery: HandoverDeliveryAttempt
    handle: LeaseHandle
    worker: str
    hook_url: str


def _takeover_attention_backoff_active(lease: HandoverExecutionLease) -> bool:
    attention_action = (
        HandoverAppAction.objects.filter(
            pk=lease.action_id,
            status=ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
        )
        .only("id", "status")
        .first()
    )
    if attention_action is None:
        return False
    last = getattr(lease, "renewed_at", None) or lease.acquired_at
    return last is not None and last > timezone.now() - timedelta(
        seconds=ASYNC_ATTENTION_POLL_INTERVAL_SECONDS,
    )


def _find_takeover_batch(
    lease: HandoverExecutionLease,
    handle: LeaseHandle,
) -> tuple[HandoverExecutionBatch, int] | None:
    batch = (
        HandoverExecutionBatch.objects.filter(
            action_id=lease.action_id,
            generation=lease.generation,
            batch_seq=lease.batch_seq,
        )
        .order_by("-id")
        .first()
    )
    if batch is None:
        _ = cas_release(handle)
        return None
    return batch, lease.action_id


def _route_async_takeover(
    action: HandoverAppAction,
    batch: HandoverExecutionBatch,
    handle: LeaseHandle,
    *,
    worker: str,
) -> HandoverAppAction | None:
    _ = cas_update_owner(handle, new_owner=f"async:{batch.id}", renew=True)
    return poll_async_action(action, worker_id=worker)


def _prepare_takeover_delivery(
    action: HandoverAppAction,
    batch: HandoverExecutionBatch,
    handle: LeaseHandle,
    *,
    worker: str,
) -> _TakeoverDelivery | None:
    hook_url = handover_hook_url(action.app)
    if not hook_url:
        logger.warning("takeover: no hook url action=%s", action.id)
        return None
    delivery = HandoverDeliveryAttempt.objects.create(
        batch=batch,
        delivery_seq=HandoverDeliveryAttempt.objects.filter(batch=batch).count() + 1,
        lease_fence=handle.fence,
        outcome=DELIVERY_OUTCOME_SENT,
    )
    handed = cas_update_owner(handle, new_owner=f"sender:{worker}", renew=True)
    if handed is None:
        return None
    return _TakeoverDelivery(action, batch, delivery, handed, worker, hook_url)


def _send_takeover_request(delivery: _TakeoverDelivery) -> HookResponse | None:
    try:
        return signed_hook_post(
            app=delivery.action.app,
            url=delivery.hook_url,
            event_type=HOOK_EVENT_EXECUTE,
            delivery_id=uuid.uuid4().hex,
            payload=dict(delivery.batch.request_payload),
        )
    except HookCallError as error:
        # 不可达: 续约, 不释放
        logger.warning("takeover unreachable action=%s error=%s", delivery.action.id, error)
        _ = cas_update_owner(delivery.handle, new_owner=delivery.worker, renew=True)
        return None


def _mark_takeover_payload_conflict(
    delivery_context: _TakeoverDelivery,
    response: HookResponse,
) -> HandoverAppAction:
    action = delivery_context.action
    batch = delivery_context.batch
    logger.error(
        "takeover payload conflict action=%s batch=%s — 转人工告警, 保持租约",
        action.id,
        batch.id,
    )
    with transaction.atomic():
        _ = require_cas(delivery_context.handle)
        action = locked_action(action.id)
        delivery = HandoverDeliveryAttempt.objects.select_for_update().get(
            pk=delivery_context.delivery.id,
        )
        delivery.outcome = DELIVERY_OUTCOME_FAILED
        delivery.http_status = int(HTTPStatus.CONFLICT)
        delivery.error_text = "takeover_payload_conflict"
        delivery.response_payload = redact_response_payload(response.payload)
        delivery.save(update_fields=["outcome", "http_status", "error_text", "response_payload"])
        action.status = ACTION_STATUS_ASYNC_ATTENTION_REQUIRED
        set_action_error(
            action,
            "takeover_payload_conflict",
            ActionErrorContext(
                stable_message="恢复重放与下游幂等记录冲突, 请人工确认真实结局",
            ),
        )
        action.save(update_fields=["status", "last_error", "last_error_raw", "updated_at"])
        handed = cas_update_owner(
            delivery_context.handle,
            new_owner=f"async:{batch.id}",
            renew=True,
        )
        if handed is None:
            raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
        record_task_event(
            action.task,
            action="handover_takeover_payload_conflict",
            actor_id=LIFECYCLE_ACTOR_ID,
            actor_type="system",
            extra={"app_key": action.app_key_snapshot, "batch_id": batch.id},
        )
    return action


def _converge_undeclared_takeover(
    action: HandoverAppAction,
    batch: HandoverExecutionBatch,
    handle: LeaseHandle,
) -> HandoverAppAction | None:
    """能力已撤销: 锁内复核 App 后一律 blocked, 失败批次, CAS 释放租约。

    执行中的动作下游结果未知, 即使能力改成 none 也不能收敛成 skipped(终态成功), 必须交人工确认。
    复核在事务内加锁读 App: 若 manifest 同步已把能力改回 declared, 返回 None 让调用方按正常路径续跑,
    否则会留下"declared 应用 + 永久 blocked 动作"的矛盾态。
    """
    with transaction.atomic():
        _ = require_cas(handle)
        app = App.objects.select_for_update().get(pk=action.app_id)
        if app.handover_capability == HANDOVER_CAPABILITY_DECLARED:
            return None
        action = locked_action(action.id)
        batch = HandoverExecutionBatch.objects.select_for_update().get(pk=batch.id)
        action.status = ACTION_STATUS_BLOCKED
        action.blocked_reason = BLOCKED_REASON_CAPABILITY_UNDECLARED
        action.save(update_fields=["status", "blocked_reason", "updated_at"])
        batch.status = BATCH_STATUS_FAILED
        batch.save(update_fields=["status"])
        _ = cas_release(handle)
        task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
        _ = refresh_task_status_locked(task)
        record_task_event(
            action.task,
            action="handover_action_blocked",
            actor_id=LIFECYCLE_ACTOR_ID,
            actor_type="system",
            extra={
                "app_key": action.app_key_snapshot,
                "blocked_reason": BLOCKED_REASON_CAPABILITY_UNDECLARED,
                "handover_capability": app.handover_capability,
            },
        )
    return action


def takeover_expired_lease(
    lease: HandoverExecutionLease,
    *,
    owner: str | None = None,
) -> HandoverAppAction | None:
    """§2.4.2 先抢占后查证: 用原 canonical body 重放 execute。"""
    worker = owner or f"recover:{uuid.uuid4().hex[:12]}"

    # async_attention_required 的 30 分钟退避必须在抢占前生效, 否则 60s recovery
    # beat 会在租约 5 分钟过期后反复 preempt+poll, 烧掉 fence 并绕过 §7 的 48 次/天 上限。
    if _takeover_attention_backoff_active(lease):
        return None

    handle = preempt_expired_lease(lease, new_owner=worker)
    if handle is None:
        return None
    takeover_batch = _find_takeover_batch(lease, handle)
    if takeover_batch is None:
        return None
    batch, action_id = takeover_batch
    return _resume_takeover(action_id, batch, handle, worker=worker)


def _resume_takeover(
    action_id: int,
    batch: HandoverExecutionBatch,
    handle: LeaseHandle,
    *,
    worker: str,
) -> HandoverAppAction | None:
    action = HandoverAppAction.objects.select_related("app", "task").get(pk=action_id)
    if action.app.handover_capability != HANDOVER_CAPABILITY_DECLARED:
        converged = _converge_undeclared_takeover(action, batch, handle)
        if converged is not None:
            return converged
        # 锁内复核时能力已恢复 declared: 重新读取后按正常路径续跑
        action = HandoverAppAction.objects.select_related("app", "task").get(pk=action_id)
    if action.status in {
        ACTION_STATUS_ASYNC_PENDING,
        ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    }:
        # 异步在途或已过 30 分钟门禁: 续约并交回 poll, 禁止重放 execute(01 §7)
        return _route_async_takeover(action, batch, handle, worker=worker)
    delivery = _prepare_takeover_delivery(action, batch, handle, worker=worker)
    if delivery is None:
        _ = cas_release(handle)
        return None
    response = _send_takeover_request(delivery)
    if response is None:
        return None
    if response.status_code == HTTPStatus.CONFLICT:
        return _mark_takeover_payload_conflict(delivery, response)
    return handle_execute_response(
        action_id=action.id,
        batch_id=batch.id,
        delivery_id=delivery.delivery.id,
        handle=delivery.handle,
        response=response,
    )
