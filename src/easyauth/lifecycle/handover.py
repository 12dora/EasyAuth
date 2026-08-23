"""交接执行与重试的生命周期编排入口。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction

from easyauth.lifecycle.handover_execution import (
    assert_action_executable,
    deliver_execute_request,
    open_execution_batch,
    retry_grant_transfer_only,
    settle_grant_only_retry,
)
from easyauth.lifecycle.handover_shared import locked_action_after_task
from easyauth.lifecycle.models import (
    ACTION_STATUS_FAILED,
    ACTION_STATUS_PREVIEWED,
    HandoverAppAction,
)

if TYPE_CHECKING:
    from easyauth.lifecycle.handover_shared import (
        GrantOnlyRetryOutcome,
        MutationGuard,
        OutboundExecution,
    )


def execute_action(
    action: HandoverAppAction,
    *,
    confirm_version: int | None = None,
    owner: str | None = None,
    mutation_guard: MutationGuard | None = None,
) -> HandoverAppAction:
    return _execute_action(
        action,
        _ExecutionSpec(
            allowed_status=ACTION_STATUS_PREVIEWED,
            confirm_version=confirm_version,
            owner=owner,
            is_retry=False,
            mutation_guard=mutation_guard,
        ),
    )


def retry_action(
    action: HandoverAppAction,
    *,
    owner: str | None = None,
    mutation_guard: MutationGuard | None = None,
) -> HandoverAppAction:
    return _execute_action(
        action,
        _ExecutionSpec(
            allowed_status=ACTION_STATUS_FAILED,
            confirm_version=None,
            owner=owner,
            is_retry=True,
            mutation_guard=mutation_guard,
        ),
    )


@dataclass(frozen=True, slots=True)
class _ExecutionSpec:
    allowed_status: str
    confirm_version: int | None
    owner: str | None
    is_retry: bool
    mutation_guard: MutationGuard | None


def _execute_action(
    action: HandoverAppAction,
    spec: _ExecutionSpec,
) -> HandoverAppAction:
    worker_owner = spec.owner or f"http:{uuid.uuid4().hex[:12]}"
    grant_only: GrantOnlyRetryOutcome | None = None
    outbound: OutboundExecution | None = None

    with transaction.atomic():
        action = locked_action_after_task(action.id)
        assert_action_executable(
            action,
            allowed_status=spec.allowed_status,
            confirm_version=spec.confirm_version,
            is_retry=spec.is_retry,
            mutation_guard=spec.mutation_guard,
        )

        # 纯授权重试: data_completed_at 非空 — 失败态提交后在 atomic 外 raise
        if spec.is_retry and action.data_completed_at is not None:
            grant_only = retry_grant_transfer_only(
                action,
                worker_owner=worker_owner,
            )
        else:
            outbound = open_execution_batch(
                action,
                worker_owner=worker_owner,
                is_retry=spec.is_retry,
            )

    if grant_only is not None:
        return settle_grant_only_retry(grant_only)

    assert outbound is not None
    return deliver_execute_request(outbound)
