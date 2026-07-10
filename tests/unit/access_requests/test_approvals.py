from __future__ import annotations

import pytest

from easyauth.access_requests.application_grants import GrantApplyFailureError
from easyauth.access_requests.approvals import (
    ApprovalActionError,
    ApprovalDecision,
    approve_access_request,
    reassign_access_request,
    reject_access_request,
)
from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_REJECTED,
    AccessRequest,
    AccessRequestGroup,
)
from easyauth.accounts.models import USER_STATUS_DEPARTED, UserMirror
from easyauth.applications.models import (
    App,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.audit.models import AuditLog
from easyauth.grants.models import AccessGrant

pytestmark = pytest.mark.django_db

APPROVER_ID = "approver-001"
GRANT_FAILURE_MESSAGE = "外部授权写入失败"


def _user_decision(actor_id: str = APPROVER_ID, comment: str = "") -> ApprovalDecision:
    return ApprovalDecision(actor_type="user", actor_id=actor_id, comment=comment)


def _admin_decision(comment: str = "") -> ApprovalDecision:
    return ApprovalDecision(actor_type="console_admin", actor_id="console-admin", comment=comment)


def test_designated_approver_approves_and_grant_is_applied() -> None:
    # Given: submitted 申请, 审批人为 approver-001。
    access_request = _submitted_request("approve-user", "approve-app")
    _ = UserMirror.objects.create(authentik_user_id=APPROVER_ID)

    # When: 指定审批人同意。
    result = approve_access_request(
        request_id=access_request.id,
        decision=_user_decision(comment="同意"),
    )

    # Then: 申请进入 grant_applied, 授权事实生成, 决定字段与审计如实记录。
    access_request.refresh_from_db()
    assert result.status == REQUEST_STATUS_GRANT_APPLIED
    assert access_request.status == REQUEST_STATUS_GRANT_APPLIED
    assert access_request.decided_by == APPROVER_ID
    assert access_request.decision_actor_type == "user"
    assert access_request.decision_comment == "同意"
    assert access_request.decided_at is not None
    assert access_request.approved_at is not None
    assert AccessGrant.objects.filter(
        user=access_request.user,
        app=access_request.app,
        is_current=True,
    ).exists()
    audit_log = AuditLog.objects.get(event_type="access_request_approved")
    assert audit_log.actor_type == "user"
    assert audit_log.actor_id == APPROVER_ID


def test_non_approver_cannot_decide() -> None:
    # Given
    access_request = _submitted_request("outsider-user", "outsider-app")

    # When / Then: 非指定审批人操作被拒, 状态与授权无变化。
    with pytest.raises(ApprovalActionError) as exc_info:
        _ = approve_access_request(
            request_id=access_request.id,
            decision=_user_decision(actor_id="stranger-001"),
        )
    access_request.refresh_from_db()
    assert exc_info.value.kind == "not_approver"
    assert access_request.status == "submitted"
    assert AccessGrant.objects.count() == 0


def test_applicant_cannot_self_approve_even_if_listed() -> None:
    # Given: 不变量被破坏的申请(申请人混入审批人列表)。
    access_request = _submitted_request("self-approve-user", "self-approve-app")
    access_request.approver_user_ids = ["self-approve-user", APPROVER_ID]
    access_request.save(update_fields=["approver_user_ids"])

    # When / Then
    with pytest.raises(ApprovalActionError) as exc_info:
        _ = approve_access_request(
            request_id=access_request.id,
            decision=_user_decision(actor_id="self-approve-user"),
        )
    assert exc_info.value.kind == "not_approver"


def test_reject_requires_comment_and_records_it() -> None:
    # Given
    access_request = _submitted_request("reject-user", "reject-app")

    # When: 无意见驳回被拒; 带意见驳回成功。
    with pytest.raises(ApprovalActionError) as exc_info:
        _ = reject_access_request(request_id=access_request.id, decision=_user_decision())
    rejected = reject_access_request(
        request_id=access_request.id,
        decision=_user_decision(comment="职责不符"),
    )

    # Then
    access_request.refresh_from_db()
    assert exc_info.value.kind == "comment_required"
    assert rejected.status == REQUEST_STATUS_REJECTED
    assert access_request.decision_comment == "职责不符"
    assert AuditLog.objects.filter(event_type="access_request_rejected").exists()
    assert AccessGrant.objects.count() == 0


def test_repeat_approve_is_idempotent_and_reject_after_approve_conflicts() -> None:
    # Given: 已由任一审批人同意的申请。
    access_request = _submitted_request(
        "idem-user",
        "idem-app",
        approvers=[APPROVER_ID, "approver-002"],
    )
    _ = approve_access_request(request_id=access_request.id, decision=_user_decision())

    # When: 另一审批人重复同意与驳回。
    repeated = approve_access_request(
        request_id=access_request.id,
        decision=_user_decision(actor_id="approver-002"),
    )
    with pytest.raises(ApprovalActionError) as exc_info:
        _ = reject_access_request(
            request_id=access_request.id,
            decision=_user_decision(actor_id="approver-002", comment="不同意"),
        )

    # Then: 重复同意幂等(授权不重复), 驳回已通过的申请是冲突。
    assert repeated.status == REQUEST_STATUS_GRANT_APPLIED
    assert exc_info.value.kind == "conflict"
    assert AccessGrant.objects.filter(is_current=True).count() == 1
    assert AuditLog.objects.filter(event_type="access_request_approved").count() == 1


def test_console_admin_decides_without_approver_membership() -> None:
    # Given
    access_request = _submitted_request("admin-decide-user", "admin-decide-app")

    # When: 控制台管理员代审(不在审批人列表)。
    result = approve_access_request(request_id=access_request.id, decision=_admin_decision())

    # Then: 生效且审计 actor_type=console_admin。
    access_request.refresh_from_db()
    assert result.status == REQUEST_STATUS_GRANT_APPLIED
    assert access_request.decision_actor_type == "console_admin"
    audit_log = AuditLog.objects.get(event_type="access_request_approved")
    assert audit_log.actor_type == "console_admin"
    assert audit_log.actor_id == "console-admin"


def test_approve_reports_committed_decision_when_grant_application_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 审批决定可提交, 但授权事实写入失败。
    access_request = _submitted_request("failed-user", "failed-app")

    def fail_grant_application(*_args: object, **_kwargs: object) -> None:
        raise GrantApplyFailureError(GRANT_FAILURE_MESSAGE)

    monkeypatch.setattr(
        "easyauth.access_requests.application.apply_grant_fact",
        fail_grant_application,
    )

    # When: 审批人同意申请。
    with pytest.raises(ApprovalActionError) as exc_info:
        _ = approve_access_request(
            request_id=access_request.id,
            decision=_user_decision(comment="同意"),
        )

    # Then: 错误明确携带“决定已提交”及最新状态, 调用方不得把它当作无副作用失败。
    access_request.refresh_from_db()
    assert access_request.status == "grant_failed"
    assert exc_info.value.kind == "application_error"
    assert exc_info.value.details == {
        "request_id": access_request.id,
        "status": "grant_failed",
        "decision_committed": True,
    }


def test_reassign_replaces_approvers_with_validation() -> None:
    # Given
    access_request = _submitted_request("reassign-user", "reassign-app")
    _ = UserMirror.objects.create(authentik_user_id="new-approver")
    _ = UserMirror.objects.create(
        authentik_user_id="departed-approver",
        status=USER_STATUS_DEPARTED,
    )

    # When: 改派到在职新审批人成功; 改派到离职者/申请人失败。
    reassigned = reassign_access_request(
        request_id=access_request.id,
        approver_user_ids=["new-approver", "new-approver", " "],
        actor_id="console-admin",
    )
    with pytest.raises(ApprovalActionError) as departed_error:
        _ = reassign_access_request(
            request_id=access_request.id,
            approver_user_ids=["departed-approver"],
            actor_id="console-admin",
        )
    with pytest.raises(ApprovalActionError) as applicant_error:
        _ = reassign_access_request(
            request_id=access_request.id,
            approver_user_ids=["reassign-user"],
            actor_id="console-admin",
        )

    # Then: 去重去空、审计包含新旧列表。
    assert reassigned.approver_user_ids == ["new-approver"]
    assert departed_error.value.kind == "validation_error"
    assert applicant_error.value.kind == "validation_error"
    audit_log = AuditLog.objects.get(event_type="access_request_reassigned")
    assert audit_log.actor_type == "console_admin"
    assert audit_log.metadata["previous_approver_user_ids"] == [APPROVER_ID]
    assert audit_log.metadata["approver_user_ids"] == ["new-approver"]


def test_reassign_rejects_non_submitted_request() -> None:
    # Given: 已驳回的申请。
    access_request = _submitted_request("reassign-done-user", "reassign-done-app")
    _ = reject_access_request(
        request_id=access_request.id,
        decision=_user_decision(comment="先驳回"),
    )
    _ = UserMirror.objects.create(authentik_user_id="late-approver")

    # When / Then
    with pytest.raises(ApprovalActionError) as exc_info:
        _ = reassign_access_request(
            request_id=access_request.id,
            approver_user_ids=["late-approver"],
            actor_id="console-admin",
        )
    assert exc_info.value.kind == "conflict"


def _submitted_request(
    user_key: str,
    app_key: str,
    *,
    approvers: list[str] | None = None,
) -> AccessRequest:
    user = UserMirror.objects.create(authentik_user_id=user_key)
    app = App.objects.create(app_key=app_key, name=app_key)
    scope = AppScope.objects.create(app=app, key="GLOBAL", name="Global")
    group = AuthorizationGroup.objects.create(app=app, key="reader", kind="role", name="Reader")
    permission = Permission.objects.create(
        app=app,
        key="reader.view",
        name="Reader View",
        supported_scopes=[scope.key],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key=scope.key,
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["rule-default-approver"],
    )
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_PERMANENT,
        approver_user_ids=approvers if approvers is not None else [APPROVER_ID],
    )
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)
    return access_request
