"""§4.5 审批责任改派。"""

from __future__ import annotations

import pytest

from easyauth.access_requests.models import (
    REQUEST_STATUS_SUBMITTED,
    AccessRequest,
    AccessRequestApprover,
)
from easyauth.accounts.models import (
    USER_STATUS_ACTIVE,
    USER_STATUS_DEPARTED,
    DingTalkUserOrgContext,
    UserMirror,
)
from easyauth.applications.models import App, ApprovalRule, AuthorizationGroup
from easyauth.audit.models import AuditLog
from easyauth.lifecycle.approvals import (
    reassign_access_request_approvers,
    replace_approval_rule_approvers,
    write_in_flight_approval_warnings,
)
from easyauth.lifecycle.models import (
    HANDOVER_KIND_OFFBOARD,
    ApprovalRuleReplacementRequired,
    HandoverAppAction,
    HandoverTask,
)
from easyauth.workflows.models import (
    APPROVAL_STATUS_SUBMITTED,
    ApprovalInstance,
    ApprovalTemplate,
)

pytestmark = pytest.mark.django_db

SOURCE = "src-ap"
CORP = "corp-ap"


def _u(uid: str, *, dtuid: str, status: str = USER_STATUS_ACTIVE) -> UserMirror:
    return UserMirror.objects.create(
        authentik_user_id=uid,
        name=uid,
        status=status,
        dingtalk_source_slug=SOURCE,
        dingtalk_corp_id=CORP,
        dingtalk_userid=dtuid,
    )


def test_reassign_access_request_approver_to_new_manager() -> None:
    departed = _u("dep", dtuid="d1", status=USER_STATUS_DEPARTED)
    applicant = _u("app", dtuid="a1")
    _ = _u("mgr", dtuid="m1")
    finance = _u("fin", dtuid="f1")
    _ = DingTalkUserOrgContext.objects.create(
        source_slug=SOURCE,
        corp_id=CORP,
        user_id="a1",
        manager_chain=[{"user_id": "m1"}],
        stale=False,
    )
    app = App.objects.create(app_key="req-app", name="req")
    ar = AccessRequest.objects.create(
        user=applicant,
        app=app,
        status=REQUEST_STATUS_SUBMITTED,
        idempotency_key="k1",
        payload_digest="0" * 64,
    )
    _ = AccessRequestApprover.objects.create(access_request=ar, approver=departed)
    _ = AccessRequestApprover.objects.create(access_request=ar, approver=finance)

    n = reassign_access_request_approvers(subject=departed)
    assert n == 1
    ids = set(
        AccessRequestApprover.objects.filter(access_request=ar).values_list(
            "approver__authentik_user_id",
            flat=True,
        ),
    )
    assert "dep" not in ids
    assert "mgr" in ids
    assert "fin" in ids  # 整体替换后保留财务


def test_zero_matching_rules_skips_assignee_resolution_and_degraded_audit() -> None:
    """V-07: 离职者未出现在任何规则时, 不得 resolve_assignee / 写 degraded 审计。"""
    departed = _u("dep-zero", dtuid="dz", status=USER_STATUS_DEPARTED)
    # 无钉钉完整绑定 → 若误 resolve 会写 handover_assignee_resolution_degraded
    departed.dingtalk_source_slug = ""
    departed.dingtalk_corp_id = ""
    departed.dingtalk_userid = ""
    departed.save()
    other = _u("other-rule", dtuid="or")
    app = App.objects.create(app_key="zero-rule-app", name="z")
    group = AuthorizationGroup.objects.create(app=app, key="g0", name="g0", kind="role")
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=[other.authentik_user_id],
        is_active=True,
    )
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=departed,
        assignee_state="superuser_pool",
    )
    before = AuditLog.objects.filter(
        event_type="handover_assignee_resolution_degraded",
    ).count()
    n = replace_approval_rule_approvers(subject=departed, task=task)
    assert n == 0
    after = AuditLog.objects.filter(
        event_type="handover_assignee_resolution_degraded",
    ).count()
    assert after == before


def test_approval_rule_replacement_todo_when_no_manager() -> None:
    departed = _u("dep2", dtuid="d2", status=USER_STATUS_DEPARTED)
    app = App.objects.create(app_key="rule-app", name="rule")
    group = AuthorizationGroup.objects.create(app=app, key="g1", name="g1", kind="role")
    rule = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=[departed.authentik_user_id],
        is_active=True,
    )
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=departed,
        assignee_state="superuser_pool",
    )
    # 无可用主管链
    n = replace_approval_rule_approvers(subject=departed, task=task)
    assert n == 0
    rule.refresh_from_db()
    # 规则不动
    assert rule.approver_userids == [departed.authentik_user_id]
    assert ApprovalRuleReplacementRequired.objects.filter(
        approval_rule=rule,
        resolved_at__isnull=True,
    ).exists()


def test_approval_rule_replacement_preserves_all_other_locked_approvers() -> None:
    departed = _u("dep-rule-current", dtuid="drc", status=USER_STATUS_DEPARTED)
    manager = _u("mgr-rule-current", dtuid="mrc")
    finance = _u("fin-rule-current", dtuid="frc")
    legal = _u("legal-rule-current", dtuid="lrc")
    _ = DingTalkUserOrgContext.objects.create(
        source_slug=SOURCE,
        corp_id=CORP,
        user_id=departed.dingtalk_userid,
        manager_chain=[{"user_id": manager.dingtalk_userid}],
        stale=False,
    )
    app = App.objects.create(app_key="rule-current-app", name="rule")
    group = AuthorizationGroup.objects.create(app=app, key="g-current", name="g", kind="role")
    rule = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=[
            departed.authentik_user_id,
            finance.authentik_user_id,
            legal.authentik_user_id,
        ],
        is_active=True,
    )
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=departed,
    )

    assert replace_approval_rule_approvers(subject=departed, task=task) == 1

    rule.refresh_from_db()
    assert rule.approver_userids == [
        finance.authentik_user_id,
        legal.authentik_user_id,
        manager.authentik_user_id,
    ]


def test_in_flight_warning_existence_only() -> None:
    subject = _u("dep3", dtuid="d3")
    app = App.objects.create(app_key="wf-app", name="wf")
    template = ApprovalTemplate.objects.create(
        app=app,
        key="t1",
        name="t",
        dingtalk_process_code="pc",
        form_schema={},
    )
    originator = _u("orig", dtuid="o1")
    _ = ApprovalInstance.objects.create(
        app=app,
        template=template,
        biz_key="bk1",
        originator_user=originator,
        status=APPROVAL_STATUS_SUBMITTED,
        payload_hash="h" * 64,
    )
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        assignee_state="superuser_pool",
    )
    action = HandoverAppAction.objects.create(task=task, app=app, status="pending")
    write_in_flight_approval_warnings(task=task, subject=subject)
    action.refresh_from_db()
    assert action.approval_instance_warning is not None
    assert "无法确认" in action.approval_instance_warning["message"]
