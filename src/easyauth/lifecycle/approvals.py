"""审批责任改派(01 §4.5): EasyAuth 自身申请 + 钉钉审批规则 + 在途实例存在性提示。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from django.db import transaction
from django.utils import timezone

from easyauth.access_requests.approvals import (
    ApprovalActionError,
    access_request_approver_user_ids,
    reassign_locked_access_request,
)
from easyauth.access_requests.models import (
    REQUEST_STATUS_SUBMITTED,
    AccessRequest,
    AccessRequestApprover,
)
from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import ApprovalRule
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.lifecycle.assignee import AssigneeResolution, resolve_assignee
from easyauth.lifecycle.core import LIFECYCLE_ACTOR_ID
from easyauth.lifecycle.errors import HandoverConflictError
from easyauth.lifecycle.models import (
    ApprovalRuleReplacementRequired,
    HandoverAppAction,
    HandoverTask,
)
from easyauth.workflows.models import APPROVAL_TERMINAL_STATUSES, ApprovalInstance

if TYPE_CHECKING:
    from easyauth.applications.ops_models import JsonValue

APPROVAL_ROUTING_NORMAL: Final = "normal"
APPROVAL_ROUTING_SUPERUSER_POOL: Final = "superuser_pool"
ROUTING_NO_ACTIVE_MANAGER: Final = "no_active_manager"
ROUTING_CHAIN_EXHAUSTED: Final = "chain_exhausted"
_APPROVER_USER_IDS_REQUIRED_MESSAGE: Final = "approver_user_ids 不能为空"
_REPLACEMENT_NOT_FOUND_MESSAGE: Final = "not_found"
_REPLACEMENT_ALREADY_RESOLVED_MESSAGE: Final = "already_resolved"
_INVALID_APPROVER_MESSAGE: Final = "存在无效或未激活的审批人"

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
        try:
            reassigned = _reassign_one_access_request(
                request_id=request_id,
                subject=subject,
                subject_pk=subject_pk,
                actor_id=actor_id,
            )
        except ApprovalActionError:
            # 单条不可改派不得回滚建单事务(§4.5 / 铁律一)。
            # 仅 submitted 可进超管池: 已决定(approved/rejected/…)的申请不得改路由/审批人。
            reassigned = _route_request_to_superuser_pool(
                request_id=request_id,
                reason=ROUTING_NO_ACTIVE_MANAGER,
                subject=subject,
                actor_id=actor_id,
                remove_subject=True,
            )
        if reassigned:
            count += 1
    return count


def _reassign_one_access_request(
    *,
    request_id: int,
    subject: UserMirror,
    subject_pk: int,
    actor_id: str,
) -> bool:
    with transaction.atomic():
        access_request = (
            AccessRequest.objects.select_for_update()
            .select_related("user", "app")
            .filter(pk=request_id)
            .first()
        )
        if access_request is None or access_request.status != REQUEST_STATUS_SUBMITTED:
            return False
        previous = access_request_approver_user_ids(access_request)
        desired = _active_surviving_approvers(previous, subject=subject)
        resolution = resolve_assignee(access_request.user, start_level=0)
        _append_resolved_approver(
            desired,
            new_approver=resolution.user,
            applicant_id=int(access_request.user_id),
            subject_pk=subject_pk,
        )

        if desired:
            _apply_normal_approval_routing(
                access_request,
                previous=previous,
                desired=desired,
                subject=subject,
                actor_id=actor_id,
            )
            return True

        reason = (
            ROUTING_NO_ACTIVE_MANAGER if resolution.degraded else ROUTING_CHAIN_EXHAUSTED
        )
        _route_locked_request_to_superuser_pool(
            access_request,
            reason=reason,
            subject=subject,
            actor_id=actor_id,
            remove_subject=True,
        )
        return True


def _active_surviving_approvers(
    previous: list[str],
    *,
    subject: UserMirror,
) -> list[str]:
    # 去掉离职者; 再过滤非 active / 本地管理员, 避免共审人失效阻断改派。
    survivor_ids = [uid for uid in previous if uid != subject.authentik_user_id]
    active_survivor_set = set(
        UserMirror.objects.filter(
            authentik_user_id__in=survivor_ids,
            status=USER_STATUS_ACTIVE,
        )
        .exclude(authentik_user_id__startswith=LOCAL_ADMIN_SUBJECT_PREFIX)
        .values_list("authentik_user_id", flat=True),
    )
    return list(dict.fromkeys(uid for uid in survivor_ids if uid in active_survivor_set))


def _append_resolved_approver(
    desired: list[str],
    *,
    new_approver: UserMirror | None,
    applicant_id: int,
    subject_pk: int,
) -> None:
    # 不得把申请人或离职者本人(仍 active 的手动建单窗口)回填为审批人。
    if new_approver is None:
        return
    if int(new_approver.pk) in {applicant_id, subject_pk}:  # type: ignore[arg-type]
        return
    if new_approver.status != USER_STATUS_ACTIVE:
        return
    if new_approver.authentik_user_id not in desired:
        desired.append(new_approver.authentik_user_id)


def _apply_normal_approval_routing(
    access_request: AccessRequest,
    *,
    previous: list[str],
    desired: list[str],
    subject: UserMirror,
    actor_id: str,
) -> None:
    reassign_locked_access_request(
        access_request=access_request,
        approver_user_ids=desired,
        actor_id=actor_id,
    )
    access_request.approval_routing_state = APPROVAL_ROUTING_NORMAL
    access_request.routing_reason = ""
    access_request.save(update_fields=["approval_routing_state", "routing_reason"])
    if set(previous) == set(desired):
        return
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


def _route_request_to_superuser_pool(
    *,
    request_id: int,
    reason: str,
    subject: UserMirror,
    actor_id: str,
    remove_subject: bool,
) -> bool:
    with transaction.atomic():
        access_request = (
            AccessRequest.objects.select_for_update()
            .filter(pk=request_id)
            .first()
        )
        if access_request is None or access_request.status != REQUEST_STATUS_SUBMITTED:
            return False
        _route_locked_request_to_superuser_pool(
            access_request,
            reason=reason,
            subject=subject,
            actor_id=actor_id,
            remove_subject=remove_subject,
        )
        return True


def _route_locked_request_to_superuser_pool(
    access_request: AccessRequest,
    *,
    reason: str,
    subject: UserMirror,
    actor_id: str,
    remove_subject: bool,
) -> None:
    if remove_subject:
        _ = AccessRequestApprover.objects.filter(
            access_request=access_request,
            approver_id=int(subject.pk),  # type: ignore[arg-type]
        ).delete()
    # 清空残余非 active 审批人
    _ = AccessRequestApprover.objects.filter(access_request=access_request).exclude(
        approver__status=USER_STATUS_ACTIVE,
    ).delete()
    access_request.approval_routing_state = APPROVAL_ROUTING_SUPERUSER_POOL
    access_request.routing_reason = reason
    access_request.save(update_fields=["approval_routing_state", "routing_reason"])
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


def replace_approval_rule_approvers(
    *,
    subject: UserMirror,
    task: HandoverTask,
    actor_id: str = LIFECYCLE_ACTOR_ID,
) -> int:
    """§4.5.2: ApprovalRule.approver_userids 中的 subject.authentik_user_id 替换为新主管。"""
    subject_uid = subject.authentik_user_id
    # 惰性解析: 仅在首条命中规则时 resolve 一次, 零命中时不写 degraded 审计、不查目录。
    resolution: AssigneeResolution | None = None

    def _resolution() -> AssigneeResolution:
        nonlocal resolution
        if resolution is None:
            resolution = resolve_assignee(subject, start_level=0)
        return resolution

    changed = 0
    with transaction.atomic():
        # JSON 列表在支持的数据库间无法用同一查询精确过滤, 先锁 active 规则再逐条判定。
        rules = list(ApprovalRule.objects.select_for_update().filter(is_active=True))
        for rule in rules:
            raw = rule.approver_userids
            if not isinstance(raw, list) or subject_uid not in raw:
                continue
            resolved = _resolution()
            new_list = _replacement_approver_ids(raw, subject=subject, resolved=resolved)

            if not new_list:
                _ensure_rule_replacement_required(
                    rule,
                    subject=subject,
                    task=task,
                    degraded=resolved.degraded,
                )
                continue

            _replace_rule_approvers(
                rule,
                new_list=new_list,
                subject_uid=subject_uid,
                task=task,
                actor_id=actor_id,
            )
            changed += 1
    return changed


def _replacement_approver_ids(
    raw: list[JsonValue],
    *,
    subject: UserMirror,
    resolved: AssigneeResolution,
) -> list[JsonValue]:
    new_list = [uid for uid in raw if uid != subject.authentik_user_id]
    new_approver = resolved.user
    if (
        new_approver is not None
        and int(new_approver.pk) != int(subject.pk)  # type: ignore[arg-type]
        and new_approver.authentik_user_id not in new_list
    ):
        new_list.append(new_approver.authentik_user_id)
    return new_list


def _ensure_rule_replacement_required(
    rule: ApprovalRule,
    *,
    subject: UserMirror,
    task: HandoverTask,
    degraded: bool,
) -> None:
    # 规则不动, 写待办(条件唯一: 同一规则+离职者仅一条未解决)
    exists = ApprovalRuleReplacementRequired.objects.filter(
        approval_rule=rule,
        departed_user=subject,
        resolved_at__isnull=True,
    ).exists()
    if exists:
        return
    _ = ApprovalRuleReplacementRequired.objects.create(
        approval_rule=rule,
        departed_user=subject,
        task=task,
        task_id_snapshot=int(task.pk),
        reason=ROUTING_NO_ACTIVE_MANAGER if degraded else ROUTING_CHAIN_EXHAUSTED,
    )


def _replace_rule_approvers(
    rule: ApprovalRule,
    *,
    new_list: list[JsonValue],
    subject_uid: str,
    task: HandoverTask,
    actor_id: str,
) -> None:
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


def write_in_flight_approval_warnings(
    *,
    task: HandoverTask,
    subject: UserMirror,
) -> None:
    """§4.5.3: 存在性提示 only — 不列条数、不按审批人过滤。"""
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
        if action.approval_instance_warning:
            continue
        # §4.5.3 要求 link 字段存在; 平台尚未存 APP 钉钉审批入口时显式标注缺口,
        # 禁止静默空串让前端当成"无链接"。
        action.approval_instance_warning = {
            "message": (
                f"本应用存在未终结的钉钉审批, 无法确认其中是否有由 "
                f"{subject.name or subject.authentik_user_id} 审批的条目, "
                f"请到钉钉中检查并人工转办。"
            ),
            "link": f"unavailable:app={action.app.app_key}",
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
        raise ValueError(_APPROVER_USER_IDS_REQUIRED_MESSAGE)
    with transaction.atomic():
        row = (
            ApprovalRuleReplacementRequired.objects.select_for_update()
            .select_related("approval_rule", "departed_user")
            .filter(pk=replacement_id)
            .first()
        )
        if row is None:
            raise LookupError(_REPLACEMENT_NOT_FOUND_MESSAGE)
        if row.resolved_at is not None:
            raise HandoverConflictError(_REPLACEMENT_ALREADY_RESOLVED_MESSAGE)
        # 校验审批人 active
        users = {
            u.authentik_user_id: u
            for u in UserMirror.objects.filter(
                authentik_user_id__in=approver_user_ids,
                status=USER_STATUS_ACTIVE,
            )
        }
        if len(users) != len(set(approver_user_ids)):
            raise ValueError(_INVALID_APPROVER_MESSAGE)
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
