"""交接单超时上交(01 §4)。代管授权已废弃, 不涉及任何 AccessGrant 变更。"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from easyauth.lifecycle.assignee import AssigneeApplyOptions, apply_assignee, resolve_assignee
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
        locked = HandoverTask.objects.select_for_update().select_related("subject_user").get(
            pk=task.id,
        )
        ensure_task_open(locked)
        start = (
            0
            if locked.assignee_state == ASSIGNEE_STATE_SUBJECT
            else locked.escalation_level + 1
        )
        previous_assignee_id = (
            locked.assignee.authentik_user_id if locked.assignee_id is not None else ""
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
            locked.assignee = None
            locked.assignee_state = ASSIGNEE_STATE_SUPERUSER_POOL
            locked.escalation_level = res.level
            locked.escalation_deadline = None
            locked.escalation_deferred_at = None
            locked.save(
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
                locked,
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
        to_assignee = (
            locked.assignee.authentik_user_id if locked.assignee is not None else ""
        )
        record_task_event(
            locked,
            action="handover_task_escalated",
            actor_id=LIFECYCLE_ACTOR_ID,
            actor_type="system",
            extra={
                "from_assignee_user_id": previous_assignee_id,
                "to_assignee": to_assignee,
                "to_assignee_state": locked.assignee_state,
                "escalation_level": locked.escalation_level,
                "at": timezone.now().isoformat(),
            },
        )
        return locked
