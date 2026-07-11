from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, override

from django.db import transaction
from django.utils import timezone

from easyauth.access_requests.application import (
    AccessRequestApplication,
    AccessRequestApplicationError,
    apply_approved_access_request,
)
from easyauth.access_requests.models import (
    DECISION_ACTOR_CONSOLE_ADMIN,
    DECISION_ACTOR_USER,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_REJECTED,
    REQUEST_STATUS_SUBMITTED,
    REQUEST_STATUS_WITHDRAWN,
    AccessRequest,
    AccessRequestApprover,
)
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from easyauth.audit.models import JsonValue

type ApprovalActionErrorKind = Literal[
    "application_error",
    "comment_required",
    "conflict",
    "not_approver",
    "not_found",
    "not_owner",
    "validation_error",
]

APPROVER_NOT_AUTHORIZED_MESSAGE = "只有该申请指定的审批人可以处理此申请。"
REQUEST_NOT_FOUND_MESSAGE = "申请不存在。"
REQUEST_ALREADY_DECIDED_MESSAGE = "该申请已被处理, 当前状态不允许此操作。"
REJECT_COMMENT_REQUIRED_MESSAGE = "驳回必须填写意见。"
REASSIGN_ONLY_SUBMITTED_MESSAGE = "只有待审批的申请可以改派审批人。"
REASSIGN_APPROVERS_REQUIRED_MESSAGE = "改派后的审批人列表不能为空。"
REASSIGN_APPLICANT_FORBIDDEN_MESSAGE = "申请人不能被指定为审批人。"
REASSIGN_APPROVER_INVALID_MESSAGE = "审批人必须是在职人员。"
WITHDRAW_ONLY_SUBMITTED_MESSAGE = "只有待审批的申请可以撤回。"


@dataclass(frozen=True, slots=True)
class ApprovalActionError(Exception):
    kind: ApprovalActionErrorKind
    message: str
    details: dict[str, JsonValue]

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    # actor_type: 站内审批人为 user; 控制台管理员代审为 console_admin(审计留痕)。
    actor_type: str
    actor_id: str
    comment: str = ""

    def is_console_admin(self) -> bool:
        return self.actor_type == DECISION_ACTOR_CONSOLE_ADMIN


def approve_access_request(*, request_id: int, decision: ApprovalDecision) -> AccessRequest:
    with transaction.atomic():
        access_request = _locked_request(request_id)
        _ensure_decision_allowed(access_request, decision)
        match access_request.status:
            case "submitted":
                _apply_decision_fields(access_request, decision, REQUEST_STATUS_APPROVED)
                access_request.approved_at = access_request.decided_at
                access_request.full_clean()
                access_request.save(
                    update_fields=[
                        "status",
                        "approved_at",
                        "decided_by",
                        "decision_actor_type",
                        "decision_comment",
                        "decided_at",
                    ],
                )
                _record_decision_event(access_request, decision, "access_request_approved")
            case "approved" | "grant_applied":
                # 任一审批人处理即生效: 重复同意幂等, 不重复记审计。
                pass
            case status:
                raise _status_conflict_error(access_request, status)
    # 授权应用沿用既有结构: 状态事务提交后独立执行, 失败自带 grant_failed 标记与重试通道;
    # grant_applied 场景下 apply 幂等返回。
    return _apply_grant(access_request, decision)


def reject_access_request(*, request_id: int, decision: ApprovalDecision) -> AccessRequest:
    if not decision.comment.strip():
        raise ApprovalActionError(
            kind="comment_required",
            message=REJECT_COMMENT_REQUIRED_MESSAGE,
            details={"request_id": request_id},
        )
    with transaction.atomic():
        access_request = _locked_request(request_id)
        _ensure_decision_allowed(access_request, decision)
        match access_request.status:
            case "submitted":
                _apply_decision_fields(access_request, decision, REQUEST_STATUS_REJECTED)
                access_request.full_clean()
                access_request.save(
                    update_fields=[
                        "status",
                        "decided_by",
                        "decision_actor_type",
                        "decision_comment",
                        "decided_at",
                    ],
                )
                _record_decision_event(access_request, decision, "access_request_rejected")
            case "rejected":
                pass
            case status:
                raise _status_conflict_error(access_request, status)
    return access_request


def withdraw_access_request(*, request_id: int, actor_user_id: str) -> AccessRequest:
    """申请人撤回待审批申请; 已撤回幂等返回。"""
    with transaction.atomic():
        access_request = _locked_request(request_id)
        if access_request.user.authentik_user_id != actor_user_id:
            # 对非所有者统一按 not_found 处理, 避免泄露他人申请是否存在。
            raise ApprovalActionError(
                kind="not_found",
                message=REQUEST_NOT_FOUND_MESSAGE,
                details={"request_id": request_id},
            )
        match access_request.status:
            case status if status == REQUEST_STATUS_SUBMITTED:
                access_request.status = REQUEST_STATUS_WITHDRAWN
                access_request.full_clean()
                access_request.save(update_fields=["status"])
                _ = AuditService.record(
                    AuditRecord(
                        actor_type=DECISION_ACTOR_USER,
                        actor_id=actor_user_id,
                        action="access_request_withdrawn",
                        target_type="access_request",
                        target_id=str(access_request.id),
                        metadata={
                            "user_id": access_request.user.authentik_user_id,
                            "app_key": access_request.app.app_key,
                        },
                    ),
                )
            case status if status == REQUEST_STATUS_WITHDRAWN:
                # 重复撤回幂等: 不重复记审计。
                pass
            case status:
                raise ApprovalActionError(
                    kind="conflict",
                    message=WITHDRAW_ONLY_SUBMITTED_MESSAGE,
                    details={"request_id": request_id, "status": status},
                )
    return access_request


def reassign_access_request(
    *,
    request_id: int,
    approver_user_ids: list[str],
    actor_id: str,
) -> AccessRequest:
    with transaction.atomic():
        access_request = _locked_request(request_id)
        if access_request.status != REQUEST_STATUS_SUBMITTED:
            raise ApprovalActionError(
                kind="conflict",
                message=REASSIGN_ONLY_SUBMITTED_MESSAGE,
                details={"request_id": request_id, "status": access_request.status},
            )
        normalized = _validated_reassign_approvers(access_request, approver_user_ids)
        previous = access_request_approver_user_ids(access_request)
        _ = AccessRequestApprover.objects.filter(access_request=access_request).delete()
        approvers = UserMirror.objects.in_bulk(normalized, field_name="authentik_user_id")
        _ = AccessRequestApprover.objects.bulk_create(
            AccessRequestApprover(
                access_request=access_request,
                approver=approvers[user_id],
            )
            for user_id in normalized
        )
        _ = AuditService.record(
            AuditRecord(
                actor_type=DECISION_ACTOR_CONSOLE_ADMIN,
                actor_id=actor_id,
                action="access_request_reassigned",
                target_type="access_request",
                target_id=str(access_request.id),
                metadata={
                    "user_id": access_request.user.authentik_user_id,
                    "app_key": access_request.app.app_key,
                    "previous_approver_user_ids": list(previous),
                    "approver_user_ids": list(normalized),
                },
            ),
        )
    return access_request


def approver_is_authorized(access_request: AccessRequest, approver_user_id: str) -> bool:
    # 申请人绝不能是审批人: 即使某条历史/非门户路径写入了这样的申请, 也必须挡住自审自批。
    if approver_user_id == access_request.user.authentik_user_id:
        return False
    return AccessRequestApprover.objects.filter(
        access_request=access_request,
        approver__authentik_user_id=approver_user_id,
    ).exists()


def access_request_approver_user_ids(access_request: AccessRequest) -> list[str]:
    assignments = getattr(access_request, "loaded_approver_assignments", None)
    if assignments is None:
        assignments = list(
            AccessRequestApprover.objects.select_related("approver").filter(
                access_request=access_request,
            ),
        )
    return [assignment.approver.authentik_user_id for assignment in assignments]


def _ensure_decision_allowed(
    access_request: AccessRequest,
    decision: ApprovalDecision,
) -> None:
    # 控制台管理员代审不受审批人列表约束(有独立审计); 站内路径必须是指定审批人。
    if decision.is_console_admin():
        return
    if not approver_is_authorized(access_request, decision.actor_id):
        raise ApprovalActionError(
            kind="not_approver",
            message=APPROVER_NOT_AUTHORIZED_MESSAGE,
            details={
                "request_id": access_request.id,
                "approver_user_id": decision.actor_id,
            },
        )


def _apply_decision_fields(
    access_request: AccessRequest,
    decision: ApprovalDecision,
    status: str,
) -> None:
    access_request.status = status
    access_request.decided_by = decision.actor_id
    access_request.decision_actor_type = (
        DECISION_ACTOR_CONSOLE_ADMIN if decision.is_console_admin() else DECISION_ACTOR_USER
    )
    access_request.decision_comment = decision.comment.strip()
    access_request.decided_at = timezone.now()


def _apply_grant(access_request: AccessRequest, decision: ApprovalDecision) -> AccessRequest:
    try:
        return apply_approved_access_request(
            AccessRequestApplication(
                request_id=access_request.id,
                actor_type=access_request.decision_actor_type or decision.actor_type,
                actor_id=decision.actor_id,
                reason=decision.comment or "站内审批通过",
            ),
        )
    except AccessRequestApplicationError as exc:
        access_request.refresh_from_db(fields=["status"])
        raise ApprovalActionError(
            kind="application_error",
            message=str(exc),
            details={
                "request_id": access_request.id,
                "status": access_request.status,
                "decision_committed": True,
            },
        ) from exc


def _validated_reassign_approvers(
    access_request: AccessRequest,
    approver_user_ids: list[str],
) -> tuple[str, ...]:
    stripped = (user_id.strip() for user_id in approver_user_ids)
    normalized = tuple(dict.fromkeys(user_id for user_id in stripped if user_id))
    if not normalized:
        raise ApprovalActionError(
            kind="validation_error",
            message=REASSIGN_APPROVERS_REQUIRED_MESSAGE,
            details={"request_id": access_request.id},
        )
    if access_request.user.authentik_user_id in normalized:
        raise ApprovalActionError(
            kind="validation_error",
            message=REASSIGN_APPLICANT_FORBIDDEN_MESSAGE,
            details={"request_id": access_request.id},
        )
    active_ids = set(
        UserMirror.objects.filter(
            authentik_user_id__in=normalized,
            status=USER_STATUS_ACTIVE,
        ).values_list("authentik_user_id", flat=True),
    )
    missing = [user_id for user_id in normalized if user_id not in active_ids]
    if missing:
        raise ApprovalActionError(
            kind="validation_error",
            message=REASSIGN_APPROVER_INVALID_MESSAGE,
            details={"request_id": access_request.id, "invalid_user_ids": list(missing)},
        )
    return normalized


def _locked_request(request_id: int) -> AccessRequest:
    access_request = (
        AccessRequest.objects.select_for_update()
        .select_related("user", "app")
        .filter(id=request_id)
        .first()
    )
    if access_request is None:
        raise ApprovalActionError(
            kind="not_found",
            message=REQUEST_NOT_FOUND_MESSAGE,
            details={"request_id": request_id},
        )
    return access_request


def _status_conflict_error(
    access_request: AccessRequest,
    status: str,
) -> ApprovalActionError:
    return ApprovalActionError(
        kind="conflict",
        message=REQUEST_ALREADY_DECIDED_MESSAGE,
        details={"request_id": access_request.id, "status": status},
    )


def _record_decision_event(
    access_request: AccessRequest,
    decision: ApprovalDecision,
    action: str,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type=access_request.decision_actor_type,
            actor_id=decision.actor_id,
            action=action,
            target_type="access_request",
            target_id=str(access_request.id),
            metadata={
                "user_id": access_request.user.authentik_user_id,
                "app_key": access_request.app.app_key,
                "decided_by": decision.actor_id,
                "comment": access_request.decision_comment,
            },
        ),
    )
