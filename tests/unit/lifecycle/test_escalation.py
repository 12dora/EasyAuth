from __future__ import annotations

import pytest
from django.utils import timezone

from easyauth.accounts.models import (
    USER_STATUS_ACTIVE,
    USER_STATUS_DEPARTED,
    DingTalkUserOrgContext,
    UserMirror,
)
from easyauth.grants.models import AccessGrant
from easyauth.lifecycle.assignee import apply_assignee, resolve_assignee
from easyauth.lifecycle.escalation import escalate_overdue_task
from easyauth.lifecycle.models import (
    ASSIGNEE_STATE_MANAGER,
    ASSIGNEE_STATE_SUBJECT,
    ASSIGNEE_STATE_SUPERUSER_POOL,
    HANDOVER_KIND_OFFBOARD,
    HANDOVER_KIND_PRE_OFFBOARD,
    HandoverTask,
)

pytestmark = pytest.mark.django_db

SOURCE = "src-e"
CORP = "corp-e"


def _user(uid: str, *, dtuid: str, status: str = USER_STATUS_ACTIVE) -> UserMirror:
    return UserMirror.objects.create(
        authentik_user_id=uid,
        name=uid,
        status=status,
        dingtalk_source_slug=SOURCE,
        dingtalk_corp_id=CORP,
        dingtalk_userid=dtuid,
    )


def _chain(subject: UserMirror, managers: list[str]) -> None:
    _ = DingTalkUserOrgContext.objects.create(
        source_slug=SOURCE,
        corp_id=CORP,
        user_id=subject.dingtalk_userid,
        manager_chain=[{"user_id": m} for m in managers],
        stale=False,
    )


def test_escalate_from_subject_starts_at_level_zero() -> None:
    """pre_offboard assignee=subject 时首次上交从直属主管开始, 不跳过 chain[0]。"""
    subject = _user("esub", dtuid="es")
    direct = _user("edir", dtuid="ed")
    upper = _user("eup", dtuid="eu")
    _ = upper
    _chain(subject, ["ed", "eu"])
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_PRE_OFFBOARD,
        subject_user=subject,
        assignee=subject,
        assignee_state=ASSIGNEE_STATE_SUBJECT,
        escalation_level=0,
        created_by=subject.authentik_user_id,
        escalation_deadline=timezone.now(),
    )
    grant_count_before = AccessGrant.objects.count()
    escalate_overdue_task(task)
    task.refresh_from_db()
    assert task.assignee_id == direct.pk
    assert task.assignee_state == ASSIGNEE_STATE_MANAGER
    assert task.escalation_level == 0
    assert AccessGrant.objects.count() == grant_count_before


def test_escalate_skips_departed_and_reaches_pool() -> None:
    subject = _user("esub2", dtuid="es2")
    _ = _user("gone", dtuid="eg", status=USER_STATUS_DEPARTED)
    _chain(subject, ["eg"])
    mgr = _user("holder", dtuid="eh")
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        created_by="admin",
    )
    apply_assignee(task, resolve_assignee(subject, start_level=0), actor_id="admin")
    # force assignee to holder then escalate past end
    task.assignee = mgr
    task.assignee_state = ASSIGNEE_STATE_MANAGER
    task.escalation_level = 0
    task.save()
    escalate_overdue_task(task)
    task.refresh_from_db()
    assert task.assignee is None
    assert task.assignee_state == ASSIGNEE_STATE_SUPERUSER_POOL
    assert task.escalation_deadline is None
