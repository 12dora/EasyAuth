"""交接单超时上交(01 §4)。代管授权已废弃, 不涉及任何 AccessGrant 变更。"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from easyauth.lifecycle.assignee import (
    AssigneeApplyOptions,
    AssigneeResolution,
    apply_assignee,
    resolve_assignee,
)
from easyauth.lifecycle.core import LIFECYCLE_ACTOR_ID, ensure_task_open, record_task_event
from easyauth.lifecycle.models import (
    ASSIGNEE_STATE_SUBJECT,
    ASSIGNEE_STATE_SUPERUSER_POOL,
    HANDOVER_ESCALATION_DAYS,
    HandoverTask,
)


def escalate_overdue_task(task: HandoverTask) -> HandoverTask:
    """上交一级; 主管链到顶则落超管池。"""
    with transaction.atomic():
        locked = _load_locked_open_task(task)
        start = _next_assignee_level(locked)
        previous_assignee = locked.assignee
        previous_assignee_id = (
            previous_assignee.authentik_user_id if previous_assignee is not None else ""
        )
        res = resolve_assignee(locked.subject_user, start_level=start)
        if res.user is not None:
            locked = apply_assignee(
                locked,
                res,
                actor_id=LIFECYCLE_ACTOR_ID,
                options=AssigneeApplyOptions(
                    actor_type="system",
                    reason="escalation",
                    set_deadline=True,
                    escalation_days=HANDOVER_ESCALATION_DAYS,
                ),
            )
        else:
            locked = _assign_superuser_pool(locked, res)
        _record_escalation_event(locked, previous_assignee_id=previous_assignee_id)
        return locked


def _load_locked_open_task(task: HandoverTask) -> HandoverTask:
    locked = (
        HandoverTask.objects.select_for_update()
        .select_related("subject_user")
        .get(
            pk=task.id,
        )
    )
    ensure_task_open(locked)
    return locked


def _next_assignee_level(task: HandoverTask) -> int:
    return 0 if task.assignee_state == ASSIGNEE_STATE_SUBJECT else task.escalation_level + 1


def _assign_superuser_pool(task: HandoverTask, res: AssigneeResolution) -> HandoverTask:
    task.assignee = None
    task.assignee_state = ASSIGNEE_STATE_SUPERUSER_POOL
    task.escalation_level = res.level
    task.escalation_deadline = None
    task.escalation_deferred_at = None
    task.save(
        update_fields=[
            "assignee",
            "assignee_state",
            "escalation_level",
            "escalation_deadline",
            "escalation_deferred_at",
            "updated_at",
        ],
    )
    record_task_event(
        task,
        action="handover_assignee_assigned",
        actor_id=LIFECYCLE_ACTOR_ID,
        actor_type="system",
        extra={
            "assignee_state": ASSIGNEE_STATE_SUPERUSER_POOL,
            "escalation_level": res.level,
            "assignee_user_id": "",
            "reason": "escalation_pool",
        },
    )
    return task


def _record_escalation_event(task: HandoverTask, *, previous_assignee_id: str) -> None:
    to_assignee = task.assignee.authentik_user_id if task.assignee is not None else ""
    record_task_event(
        task,
        action="handover_task_escalated",
        actor_id=LIFECYCLE_ACTOR_ID,
        actor_type="system",
        extra={
            "from_assignee_user_id": previous_assignee_id,
            "to_assignee": to_assignee,
            "to_assignee_state": task.assignee_state,
            "escalation_level": task.escalation_level,
            "at": timezone.now().isoformat(),
        },
    )
