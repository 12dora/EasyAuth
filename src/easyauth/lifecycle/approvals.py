"""审批责任改派(01 §4.5): EasyAuth 自身申请 + 钉钉审批规则 + 在途实例存在性提示。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from django.db import transaction
from django.utils import timezone

from easyauth.access_requests.approvals import (
    access_request_approver_user_ids,
    reassign_access_request,
)
from easyauth.access_requests.models import (
    REQUEST_STATUS_SUBMITTED,
    AccessRequest,
    AccessRequestApprover,
)
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import ApprovalRule
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.lifecycle.assignee import resolve_assignee
from easyauth.lifecycle.core import LIFECYCLE_ACTOR_ID, record_task_event
from easyauth.lifecycle.models import ApprovalRuleReplacementRequired, HandoverAppAction, HandoverTask
from easyauth.workflows.models import ApprovalInstance

if TYPE_CHECKING:
    from easyauth.applications.ops_models import JsonValue

APPROVAL_ROUTING_NORMAL: Final = "normal"
APPROVAL_ROUTING_SUPERUSER_POOL: Final = "superuser_pool"
ROUTING_NO_ACTIVE_MANAGER: Final = "no_active_manager"
ROUTING_CHAIN_EXHAUSTED: Final = "chain_exhausted"

IN_FLIGHT_INSTANCE_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "running",
        "NEW",
        "RUNNING",
        "pending",
        "in_progress",
    },
)


def reassign_approvals_for_departed(
    *,
    subject: UserMirror,
    task: HandoverTask,
    actor_id: str = LIFECYCLE_ACTOR_ID,
) -> None:
    """离职建单同事务内调用: §4.5.1 + §4.5.2 + §4.5.3 警示写入。"""
    reassign_access_request_approvers(subject=subject, actor_id=actor_id)
    replace_approval_rule_approvers(subject=subject, task=task, actor_id=actor_id)
    write_in_flight_approval_warnings(task=task, subject=subject)


def reassign_access_request_approvers(
    *,
    subject: UserMirror,
    actor_id: str = LIFECYCLE_ACTOR_ID,
) -> int:
    """§4.5.1: submitted 申请中, 审批人是 subject 的行 → 替换为申请人主管链解析结果。"""
    subject_pk = int(subject.pk)  # type: ignore[arg-type]
    assignment_ids = list(
        AccessRequestApprover.objects.filter(
            approver_id=subject_pk,
            access_request__status=REQUEST_STATUS_SUBMITTED,
        ).values_list("access_request_id", flat=True),
    )
    if not assignment_ids:
        return 0
    count = 0
    for request_id in set(assignment_ids):
        access_request = (
            AccessRequest.objects.select_related("user")
            .filter(pk=request_id, status=REQUEST_STATUS_SUBMITTED)
            .first()
        )
        if access_request is None:
            continue
        previous = access_request_approver_user_ids(access_request)
        desired = [uid for uid in previous if uid != subject.authentik_user_id]
        resolution = resolve_assignee(access_request.user, start_level=0)
        new_approver = resolution.user
        if (
            new_approver is not None
            and int(new_approver.pk) != int(access_request.user_id)  # type: ignore[arg-type]
            and new_approver.authentik_user_id not in desired
        ):
            desired.append(new_approver.authentik_user_id)

        if desired:
            reassign_access_request(
                request_id=int(access_request.id),
                approver_user_ids=desired,
                actor_id=actor_id,
            )
            if hasattr(access_request, "approval_routing_state"):
                access_request.approval_routing_state = APPROVAL_ROUTING_NORMAL
                access_request.routing_reason = ""
                access_request.save(
                    update_fields=["approval_routing_state", "routing_reason"],
                )
            _ = AuditService.record(
                AuditRecord(
                    actor_type="system",
                    actor_id=actor_id,
                    action="handover_approver_reassigned",
                    target_type="access_request",
                    target_id=str(access_request.id),
                    metadata={
                        "departed_user_id": subject.authentik_user_id,
                        "approver_user_ids": desired,
                    },
                ),
            )
        else:
            # 删除离职者审批行, 保持 submitted, 进超管池
            _ = AccessRequestApprover.objects.filter(
                access_request=access_request,
                approver_id=subject_pk,
            ).delete()
            reason = (
                ROUTING_NO_ACTIVE_MANAGER
                if resolution.degraded
                else ROUTING_CHAIN_EXHAUSTED
            )
            if hasattr(access_request, "approval_routing_state"):
                access_request.approval_routing_state = APPROVAL_ROUTING_SUPERUSER_POOL
                access_request.routing_reason = reason
                access_request.save(
                    update_fields=["approval_routing_state", "routing_reason"],
                )
            _ = AuditService.record(
                AuditRecord(
                    actor_type="system",
                    actor_id=actor_id,
                    action="handover_approver_reassigned",
                    target_type="access_request",
                    target_id=str(access_request.id),
                    metadata={
                        "departed_user_id": subject.authentik_user_id,
                        "approval_routing_state": APPROVAL_ROUTING_SUPERUSER_POOL,
                        "routing_reason": reason,
                    },
                ),
            )
        count += 1
    return count


def replace_approval_rule_approvers(
    *,
    subject: UserMirror,
    task: HandoverTask,
    actor_id: str = LIFECYCLE_ACTOR_ID,
) -> int:
    """§4.5.2: ApprovalRule.approver_userids 中的 subject.authentik_user_id 替换为新主管。"""
    subject_uid = subject.authentik_user_id
    rules = list(ApprovalRule.objects.filter(is_active=True))
    changed = 0
    for rule in rules:
        raw = rule.approver_userids
        if not isinstance(raw, list) or subject_uid not in raw:
            continue
        resolution = resolve_assignee(subject, start_level=0)
        new_approver = resolution.user
        new_list = [uid for uid in raw if uid != subject_uid]
        if new_approver is not None and new_approver.authentik_user_id not in new_list:
            new_list.append(new_approver.authentik_user_id)

        if not new_list:
            # 规则不动, 写待办(条件唯一: 同一规则+离职者仅一条未解决)
            exists = ApprovalRuleReplacementRequired.objects.filter(
                approval_rule=rule,
                departed_user=subject,
                resolved_at__isnull=True,
            ).exists()
            if not exists:
                _ = ApprovalRuleReplacementRequired.objects.create(
                    approval_rule=rule,
                    departed_user=subject,
                    task=task,
                    task_id_snapshot=int(task.pk),
                    reason=(
                        ROUTING_NO_ACTIVE_MANAGER
                        if resolution.degraded
                        else ROUTING_CHAIN_EXHAUSTED
                    ),
                )
            continue

        rule.approver_userids = new_list
        rule.save(update_fields=["approver_userids", "updated_at"])
        _ = AuditService.record(
            AuditRecord(
                actor_type="system",
                actor_id=actor_id,
                action="handover_approval_rule_approver_replaced",
                target_type="approval_rule",
                target_id=str(rule.id),
                metadata={
                    "departed_user_id": subject_uid,
                    "approver_userids": new_list,
                    "task_id": task.id,
                },
            ),
        )
        changed += 1
    return changed


def write_in_flight_approval_warnings(
    *,
    task: HandoverTask,
    subject: UserMirror,
) -> None:
    """§4.5.3: 存在性提示 only — 不列条数、不按审批人过滤。"""
    from easyauth.workflows.models import APPROVAL_TERMINAL_STATUSES

    now = timezone.now().isoformat()
    actions = HandoverAppAction.objects.select_related("app").filter(task=task)
    for action in actions:
        has_open = (
            ApprovalInstance.objects.filter(app=action.app)
            .exclude(status__in=APPROVAL_TERMINAL_STATUSES)
            .exists()
        )
        if not has_open:
            continue
        # 已有持久化警示不覆盖(升级也不清)
        if action.approval_instance_warning:
            continue
        action.approval_instance_warning = {
            "message": (
                f"本应用存在未终结的钉钉审批，无法确认其中是否有由 "
                f"{subject.name or subject.authentik_user_id} 审批的条目，"
                f"请到钉钉中检查并人工转办。"
            ),
            "link": "",
            "recorded_at": now,
        }
        action.save(update_fields=["approval_instance_warning", "updated_at"])


def resolve_approval_rule_replacement(
    replacement_id: int,
    *,
    approver_user_ids: list[str],
    actor_id: str,
) -> ApprovalRuleReplacementRequired:
    """控制台解决待办: 同事务锁 + 替换 + resolved。"""
    if not approver_user_ids:
        raise ValueError("approver_user_ids 不能为空")
    with transaction.atomic():
        row = (
            ApprovalRuleReplacementRequired.objects.select_for_update()
            .select_related("approval_rule", "departed_user")
            .filter(pk=replacement_id)
            .first()
        )
        if row is None:
            raise LookupError("not_found")
        if row.resolved_at is not None:
            from easyauth.lifecycle.errors import HandoverConflictError

            raise HandoverConflictError("already_resolved")
        # 校验审批人 active
        users = {
            u.authentik_user_id: u
            for u in UserMirror.objects.filter(
                authentik_user_id__in=approver_user_ids,
                status=USER_STATUS_ACTIVE,
            )
        }
        if len(users) != len(set(approver_user_ids)):
            raise ValueError("存在无效或未激活的审批人")
        rule = ApprovalRule.objects.select_for_update().get(pk=row.approval_rule_id)
        rule.approver_userids = list(dict.fromkeys(approver_user_ids))
        rule.save(update_fields=["approver_userids", "updated_at"])
        row.resolved_at = timezone.now()
        row.resolved_by = actor_id
        row.save(update_fields=["resolved_at", "resolved_by"])
        _ = AuditService.record(
            AuditRecord(
                actor_type="admin",
                actor_id=actor_id,
                action="handover_approval_rule_approver_replaced",
                target_type="approval_rule",
                target_id=str(rule.id),
                metadata={
                    "replacement_id": row.id,
                    "approver_userids": rule.approver_userids,
                    "manual_resolution": True,
                },
            ),
        )
        return row
