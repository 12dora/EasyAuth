"""主管链解析与 assignee 写入(01 §3)。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from django.utils import timezone

from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import (
    USER_STATUS_ACTIVE,
    DingTalkUserOrgContext,
    UserMirror,
)
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.lifecycle.core import LIFECYCLE_ACTOR_ID, record_task_event
from easyauth.lifecycle.models import (
    ASSIGNEE_STATE_MANAGER,
    ASSIGNEE_STATE_SUPERUSER_POOL,
    HANDOVER_ESCALATION_DAYS,
    HandoverTask,
)

if TYPE_CHECKING:
    from easyauth.applications.ops_models import JsonValue


@dataclass(frozen=True, slots=True)
class AssigneeResolution:
    user: UserMirror | None
    state: str
    level: int
    degraded: bool


def resolve_assignee(subject: UserMirror, *, start_level: int = 0) -> AssigneeResolution:
    """沿 manager_chain 自 start_level 向上找第一个可用主管。"""
    if not subject.dingtalk_source_slug or not subject.dingtalk_corp_id or not subject.dingtalk_userid:
        _audit_subject(
            subject,
            action="handover_assignee_resolution_degraded",
            extra={"reason": "missing_dingtalk_binding"},
        )
        return AssigneeResolution(
            user=None,
            state=ASSIGNEE_STATE_SUPERUSER_POOL,
            level=0,
            degraded=True,
        )
    context = DingTalkUserOrgContext.objects.filter(
        source_slug=subject.dingtalk_source_slug,
        corp_id=subject.dingtalk_corp_id,
        user_id=subject.dingtalk_userid,
    ).first()
    if context is None or context.stale or not context.manager_chain:
        _audit_subject(
            subject,
            action="handover_assignee_resolution_degraded",
            extra={"reason": "directory_unavailable_or_stale"},
        )
        return AssigneeResolution(
            user=None,
            state=ASSIGNEE_STATE_SUPERUSER_POOL,
            level=0,
            degraded=True,
        )
    chain = context.manager_chain
    if not isinstance(chain, list):
        _audit_subject(
            subject,
            action="handover_assignee_resolution_degraded",
            extra={"reason": "manager_chain_not_list"},
        )
        return AssigneeResolution(
            user=None,
            state=ASSIGNEE_STATE_SUPERUSER_POOL,
            level=0,
            degraded=True,
        )
    level = max(0, start_level)
    while level < len(chain):
        entry = chain[level]
        if not isinstance(entry, dict):
            _audit_subject(
                subject,
                action="handover_assignee_chain_entry_malformed",
                extra={"level": level, "entry": str(entry)[:200]},
            )
            level += 1
            continue
        manager_userid = entry.get("user_id")
        if not isinstance(manager_userid, str) or not manager_userid:
            _audit_subject(
                subject,
                action="handover_assignee_chain_entry_malformed",
                extra={"level": level},
            )
            level += 1
            continue
        manager = UserMirror.objects.filter(
            dingtalk_source_slug=subject.dingtalk_source_slug,
            dingtalk_corp_id=subject.dingtalk_corp_id,
            dingtalk_userid=manager_userid,
        ).first()
        if (
            manager is None
            or manager.status != USER_STATUS_ACTIVE
            or manager.authentik_user_id.startswith(LOCAL_ADMIN_SUBJECT_PREFIX)
            or int(manager.pk) == int(subject.pk)  # type: ignore[arg-type]
        ):
            level += 1
            continue
        return AssigneeResolution(
            user=manager,
            state=ASSIGNEE_STATE_MANAGER,
            level=level,
            degraded=False,
        )
    return AssigneeResolution(
        user=None,
        state=ASSIGNEE_STATE_SUPERUSER_POOL,
        level=len(chain),
        degraded=False,
    )


def apply_assignee(
    task: HandoverTask,
    resolution: AssigneeResolution,
    *,
    actor_id: str,
    actor_type: str = "system",
    reason: str = "",
    set_deadline: bool = True,
    escalation_days: int = HANDOVER_ESCALATION_DAYS,
) -> HandoverTask:
    """写 assignee 字段 + 审计。调用方须已在同一事务内锁住 task。"""
    task.assignee = resolution.user
    task.assignee_state = resolution.state
    task.escalation_level = resolution.level
    update_fields = [
        "assignee",
        "assignee_state",
        "escalation_level",
        "updated_at",
    ]
    if set_deadline:
        if resolution.state == ASSIGNEE_STATE_SUPERUSER_POOL:
            task.escalation_deadline = None
        else:
            task.escalation_deadline = timezone.now() + timedelta(days=escalation_days)
        update_fields.append("escalation_deadline")
    if task.escalation_deferred_at is not None:
        task.escalation_deferred_at = None
        update_fields.append("escalation_deferred_at")
    task.save(update_fields=update_fields)
    record_task_event(
        task,
        action="handover_assignee_assigned",
        actor_id=actor_id,
        actor_type=actor_type,
        extra={
            "assignee_state": resolution.state,
            "escalation_level": resolution.level,
            "assignee_user_id": (
                resolution.user.authentik_user_id if resolution.user is not None else ""
            ),
            "reason": reason,
            "degraded": resolution.degraded,
        },
    )
    return task


def _audit_subject(
    subject: UserMirror,
    *,
    action: str,
    extra: dict[str, JsonValue] | None = None,
) -> None:
    metadata: dict[str, JsonValue] = {
        "subject_user_id": subject.authentik_user_id,
    }
    if extra:
        metadata.update(extra)
    _ = AuditService.record(
        AuditRecord(
            actor_type="system",
            actor_id=LIFECYCLE_ACTOR_ID,
            action=action,
            target_type="user_mirror",
            target_id=subject.authentik_user_id,
            metadata=metadata,
        ),
    )
