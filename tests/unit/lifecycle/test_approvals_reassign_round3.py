"""Round-3 approval reassignment regressions."""

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
    USER_STATUS_DISABLED,
    DingTalkUserOrgContext,
    UserMirror,
)
from easyauth.applications.models import App
from easyauth.lifecycle.approvals import reassign_access_request_approvers
from easyauth.lifecycle.models import HANDOVER_KIND_OFFBOARD, HandoverTask

pytestmark = pytest.mark.django_db

SOURCE = "src-r3"
CORP = "corp-r3"


def _u(uid: str, *, dtuid: str, status: str = USER_STATUS_ACTIVE) -> UserMirror:
    return UserMirror.objects.create(
        authentik_user_id=uid,
        name=uid,
        status=status,
        dingtalk_source_slug=SOURCE,
        dingtalk_corp_id=CORP,
        dingtalk_userid=dtuid,
    )


def test_disabled_co_approver_does_not_abort_reassignment() -> None:
    """非 active 共审人不得让整次离职建单的审批改派抛错。"""
    departed = _u("dep-r3", dtuid="d1", status=USER_STATUS_DEPARTED)
    applicant = _u("app-r3", dtuid="a1")
    new_mgr = _u("mgr-r3", dtuid="m1")
    finance = _u("fin-r3", dtuid="f1", status=USER_STATUS_DISABLED)
    _ = DingTalkUserOrgContext.objects.create(
        source_slug=SOURCE,
        corp_id=CORP,
        user_id="a1",
        manager_chain=[{"user_id": "m1"}],
        stale=False,
    )
    app = App.objects.create(app_key="req-app-r3", name="req")
    ar = AccessRequest.objects.create(
        user=applicant,
        app=app,
        status=REQUEST_STATUS_SUBMITTED,
        idempotency_key="k-r3-1",
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
    assert "dep-r3" not in ids
    assert "fin-r3" not in ids  # disabled 被过滤
    assert "mgr-r3" in ids
    ar.refresh_from_db()
    assert ar.approval_routing_state == "normal"


def test_still_active_subject_not_reinstated_as_approver() -> None:
    """手动建单窗口 subject 仍 active 时, 不得把自己回填为审批人。"""
    subject = _u("dep-active", dtuid="d2")  # 仍 active
    applicant = _u("app2", dtuid="a2")
    # 申请人的主管链第一环就是离职者本人
    _ = DingTalkUserOrgContext.objects.create(
        source_slug=SOURCE,
        corp_id=CORP,
        user_id="a2",
        manager_chain=[{"user_id": "d2"}],
        stale=False,
    )
    app = App.objects.create(app_key="req-app-r3b", name="req")
    ar = AccessRequest.objects.create(
        user=applicant,
        app=app,
        status=REQUEST_STATUS_SUBMITTED,
        idempotency_key="k-r3-2",
        payload_digest="1" * 64,
    )
    _ = AccessRequestApprover.objects.create(access_request=ar, approver=subject)

    n = reassign_access_request_approvers(subject=subject)
    assert n == 1
    ids = list(
        AccessRequestApprover.objects.filter(access_request=ar).values_list(
            "approver__authentik_user_id",
            flat=True,
        ),
    )
    assert "dep-active" not in ids
    ar.refresh_from_db()
    assert ar.approval_routing_state == "superuser_pool"


def test_already_approved_request_not_routed_to_pool_on_reassign_conflict() -> None:
    """并发审批通过后, ApprovalActionError 回落不得改写已决定申请的路由/审批人。"""
    from easyauth.access_requests.approvals import ApprovalActionError
    from easyauth.access_requests.models import REQUEST_STATUS_APPROVED
    from easyauth.lifecycle import approvals as approvals_mod

    departed = _u("dep-approved", dtuid="da", status=USER_STATUS_DEPARTED)
    applicant = _u("app-approved", dtuid="aa")
    co_approver = _u("co-approved", dtuid="ca")
    app = App.objects.create(app_key="req-app-approved", name="req")
    ar = AccessRequest.objects.create(
        user=applicant,
        app=app,
        status=REQUEST_STATUS_SUBMITTED,
        idempotency_key="k-r3-approved",
        payload_digest="a" * 64,
        approval_routing_state="normal",
        routing_reason="",
    )
    _ = AccessRequestApprover.objects.create(access_request=ar, approver=departed)
    _ = AccessRequestApprover.objects.create(access_request=ar, approver=co_approver)

    # 模拟竞态: 扫描时仍 submitted, 锁内改派瞬间已被并发批准
    def _flip_and_conflict(**_kwargs: object) -> bool:
        from django.utils import timezone

        now = timezone.now()
        AccessRequest.objects.filter(pk=ar.pk).update(
            status=REQUEST_STATUS_APPROVED,
            approved_at=now,
            decided_at=now,
            decided_by="co-approved",
            decision_actor_type="user",
            decision_comment="concurrent approve",
        )
        raise ApprovalActionError(
            kind="conflict",
            message="only submitted can be reassigned",
            details={"request_id": ar.id, "status": REQUEST_STATUS_APPROVED},
        )

    original = approvals_mod._reassign_one_access_request
    approvals_mod._reassign_one_access_request = _flip_and_conflict  # type: ignore[assignment]
    try:
        n = reassign_access_request_approvers(subject=departed)
    finally:
        approvals_mod._reassign_one_access_request = original  # type: ignore[assignment]

    assert n == 0
    ar.refresh_from_db()
    assert ar.status == REQUEST_STATUS_APPROVED
    assert ar.approval_routing_state == "normal"
    assert ar.routing_reason == ""
    remaining = set(
        AccessRequestApprover.objects.filter(access_request=ar).values_list(
            "approver__authentik_user_id",
            flat=True,
        ),
    )
    assert remaining == {"dep-approved", "co-approved"}
