"""交接数据阶段的分事务收尾流程。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from django.db import transaction
from django.utils import timezone

from easyauth.lifecycle.core import (
    record_task_event,
    refresh_task_status_locked,
)
from easyauth.lifecycle.errors import HandoverError
from easyauth.lifecycle.lease import (
    LeaseHandle,
    must_cas_release,
    require_cas,
)
from easyauth.lifecycle.models import (
    ACTION_GRANT_TRANSFER_KINDS,
    ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    ACTION_STATUS_ASYNC_PENDING,
    ACTION_STATUS_DONE,
    ACTION_STATUS_EXECUTING,
    ACTION_STATUS_FAILED,
    ACTION_STATUS_PREVIEWED,
    BATCH_STATUS_DATA_COMPLETED,
    BATCH_STATUS_DONE,
    BATCH_STATUS_FAILED,
    HandoverAppAction,
    HandoverExecutionBatch,
    HandoverTask,
)
from easyauth.lifecycle.transfer import transfer_selected_grants

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.applications.ops_models import JsonValue

from easyauth.lifecycle.handover_payloads import (
    bump_plan_progress,
    complete_active_plan,
)
from easyauth.lifecycle.handover_shared import (
    ActionErrorContext,
    DataPhaseAudit,
    DataPhaseGate,
    locked_action_after_task,
    set_action_error,
)
from easyauth.lifecycle.handover_validation import (
    merge_result_summary,
    validate_execute_summary_conservation,
)


@dataclass(frozen=True, slots=True)
class CompleteDataPhaseSpec:
    """数据阶段收尾所需参数。"""

    handle: LeaseHandle
    response_payload: dict[str, JsonValue] | None = None
    enforce_conservation: bool = True
    summary_unknown: bool = False
    audit: DataPhaseAudit = field(
        default_factory=lambda: DataPhaseAudit(
            actor_id=None,
            actor_type="system",
            extra=None,
        ),
    )


def complete_data_phase(
    batch: HandoverExecutionBatch,
    spec: CompleteDataPhaseSpec,
) -> None:
    """同步 200 与异步终态汇合的收尾(01 §5.5)。A/B/C 必须各自 commit。

    ``enforce_conservation=False`` 仅用于 async-abandon 人工确认路径:
    超管已在下游确认结局, 不得再被陈旧 preview count 挡住唯一出口。
    """
    action_id = batch.action_id
    batch_pk = cast("int", batch.pk)

    # —— 事务 A: 守恒校验 + data_completed 标记必须先提交, 授权失败也不能丢 ——
    gate = _commit_data_completion(batch, spec)
    if gate.conservation_fail is not None:
        # 与事务 B 一致: 先提交 failed + 释放, 再在 atomic 外 raise,
        # 避免守恒失败状态被 Django 回滚(01 §7 / 00 §10.5)。
        raise HandoverError(gate.conservation_fail)
    if gate.settled_non_final:
        return

    # —— 事务 B: 仅 offboard 转授权; 失败写 failed+释放并提交, 再 raise ——
    if gate.needs_grant and action_id is not None:
        _transfer_grants_for_data_phase(
            batch_pk=batch_pk,
            action_id=int(action_id),
            handle=spec.handle,
        )

    # —— 事务 C: done + 清空 snapshot_token + 释放 ——
    _finalize_data_phase(
        batch_pk=batch_pk,
        action_id=action_id,
        handle=spec.handle,
        audit=spec.audit,
    )


def _record_data_phase_audit(action: HandoverAppAction, audit: DataPhaseAudit) -> None:
    if audit.actor_id is None or audit.extra is None:
        return
    record_task_event(
        action.task,
        action="handover_action_executed",
        actor_id=audit.actor_id,
        actor_type=audit.actor_type,
        extra=audit.extra,
    )


def _commit_data_completion(
    batch: HandoverExecutionBatch,
    spec: CompleteDataPhaseSpec,
) -> DataPhaseGate:
    action_id = batch.action_id
    is_final = batch.is_final
    with transaction.atomic():
        require_cas(spec.handle)
        batch = HandoverExecutionBatch.objects.select_for_update().get(pk=batch.pk)
        now = timezone.now()
        first_data_completion = batch.data_completed_at is None

        action = locked_action_after_task(int(action_id)) if action_id is not None else None
        if (
            action is not None
            and spec.enforce_conservation
            and first_data_completion
            and _fail_batch_on_conservation_breach(
                action,
                batch,
                handle=spec.handle,
                response_payload=spec.response_payload,
            )
        ):
            return DataPhaseGate(conservation_fail="summary_conservation_failed")

        if first_data_completion:
            batch.status = BATCH_STATUS_DATA_COMPLETED
            batch.data_completed_at = now
            batch.save(update_fields=["status", "data_completed_at"])
            if action is not None:
                _apply_result_summary(
                    action,
                    response_payload=spec.response_payload,
                    summary_unknown=spec.summary_unknown,
                )

        if not is_final:
            _settle_non_final_batch(
                batch,
                action,
                handle=spec.handle,
                first_data_completion=first_data_completion,
                audit=spec.audit,
            )
            return DataPhaseGate(settled_non_final=True)

        needs_grant = _mark_action_data_completed(action, batch=batch, now=now)
    return DataPhaseGate(needs_grant=needs_grant)


def _fail_batch_on_conservation_breach(
    action: HandoverAppAction,
    batch: HandoverExecutionBatch,
    *,
    handle: LeaseHandle,
    response_payload: dict[str, JsonValue] | None,
) -> bool:
    """守恒不成立时就地写 failed + 释放租约并返回 True; 由调用方在 atomic 外 raise。"""
    conservation_error = validate_execute_summary_conservation(
        action,
        response_payload=response_payload,
    )
    if conservation_error is None:
        return False
    action.status = ACTION_STATUS_FAILED
    set_action_error(action, conservation_error)
    action.save(
        update_fields=[
            "status",
            "last_error",
            "last_error_raw",
            "updated_at",
        ],
    )
    batch.status = BATCH_STATUS_FAILED
    batch.save(update_fields=["status"])
    must_cas_release(handle)
    task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
    _ = refresh_task_status_locked(task)
    return True


def _mark_action_data_completed(
    action: HandoverAppAction | None,
    *,
    batch: HandoverExecutionBatch,
    now: datetime,
) -> bool:
    """最终批: 记下 action 的 data_completed_at, 返回是否还需要转授权。"""
    if action is None:
        return False
    action.data_completed_at = action.data_completed_at or batch.data_completed_at or now
    action.save(
        update_fields=["data_completed_at", "result_summary", "updated_at"],
    )
    return action.task.kind in ACTION_GRANT_TRANSFER_KINDS


def _apply_result_summary(
    action: HandoverAppAction,
    *,
    response_payload: dict[str, JsonValue] | None,
    summary_unknown: bool,
) -> None:
    if response_payload is not None:
        merge_result_summary(action, response_payload)
    elif summary_unknown:
        action.result_summary = None


def _settle_non_final_batch(
    batch: HandoverExecutionBatch,
    action: HandoverAppAction | None,
    *,
    handle: LeaseHandle,
    first_data_completion: bool,
    audit: DataPhaseAudit,
) -> None:
    batch.status = BATCH_STATUS_DONE
    batch.save(update_fields=["status"])
    if action is not None:
        # 非最终批: 同步 executing 与异步 async_* 都要退回 previewed 并释放租约。
        if action.status in {
            ACTION_STATUS_EXECUTING,
            ACTION_STATUS_ASYNC_PENDING,
            ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
        }:
            action.status = ACTION_STATUS_PREVIEWED
            action.snapshot_token = ""
            action.async_status_url = ""
            action.save(
                update_fields=[
                    "status",
                    "snapshot_token",
                    "async_status_url",
                    "result_summary",
                    "updated_at",
                ],
            )
        if first_data_completion:
            bump_plan_progress(action)
        _record_data_phase_audit(action, audit)
    must_cas_release(handle)


def _transfer_grants_for_data_phase(
    *,
    batch_pk: int,
    action_id: int,
    handle: LeaseHandle,
) -> None:
    grant_error: Exception | None = None
    with transaction.atomic():
        require_cas(handle)
        action = locked_action_after_task(action_id)
        batch = HandoverExecutionBatch.objects.select_for_update().get(pk=batch_pk)
        try:
            _ = transfer_selected_grants(action)
        except Exception as error:
            action.status = ACTION_STATUS_FAILED
            set_action_error(
                action,
                error,
                ActionErrorContext(stable_message="授权转移失败"),
            )
            action.save(
                update_fields=["status", "last_error", "last_error_raw", "updated_at"],
            )
            batch.status = BATCH_STATUS_FAILED
            batch.save(update_fields=["status"])
            must_cas_release(handle)
            task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
            _ = refresh_task_status_locked(task)
            grant_error = error
    if grant_error is not None:
        raise HandoverError("授权转移失败") from grant_error


def _finalize_data_phase(
    *,
    batch_pk: int,
    action_id: int | None,
    handle: LeaseHandle,
    audit: DataPhaseAudit,
) -> None:
    with transaction.atomic():
        require_cas(handle)
        batch = HandoverExecutionBatch.objects.select_for_update().get(pk=batch_pk)
        if action_id is not None:
            action = locked_action_after_task(int(action_id))
            action.status = ACTION_STATUS_DONE
            action.async_status_url = ""
            action.last_error = ""
            action.snapshot_token = ""
            action.save(
                update_fields=[
                    "status",
                    "async_status_url",
                    "last_error",
                    "snapshot_token",
                    "updated_at",
                ],
            )
            complete_active_plan(action)
            task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
            _ = refresh_task_status_locked(task)
            _record_data_phase_audit(action, audit)
        batch.status = BATCH_STATUS_DONE
        batch.save(update_fields=["status"])
        must_cas_release(handle)
