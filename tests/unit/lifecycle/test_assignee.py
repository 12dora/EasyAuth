from __future__ import annotations

import pytest

from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import (
    USER_STATUS_ACTIVE,
    USER_STATUS_DEPARTED,
    DingTalkUserOrgContext,
    UserMirror,
)
from easyauth.lifecycle.assignee import apply_assignee, resolve_assignee
from easyauth.lifecycle.models import (
    ASSIGNEE_STATE_MANAGER,
    ASSIGNEE_STATE_SUPERUSER_POOL,
    HANDOVER_KIND_OFFBOARD,
    HandoverTask,
)

pytestmark = pytest.mark.django_db

SOURCE = "src-a"
CORP = "corp-a"


def _user(uid: str, *, dtuid: str, status: str = USER_STATUS_ACTIVE) -> UserMirror:
    return UserMirror.objects.create(
        authentik_user_id=uid,
        name=uid,
        status=status,
        dingtalk_source_slug=SOURCE,
        dingtalk_corp_id=CORP,
        dingtalk_userid=dtuid,
    )


def _chain(subject: UserMirror, manager_dtuids: list[str], *, stale: bool = False) -> None:
    _ = DingTalkUserOrgContext.objects.create(
        source_slug=SOURCE,
        corp_id=CORP,
        user_id=subject.dingtalk_userid,
        manager_chain=[{"user_id": m} for m in manager_dtuids],
        stale=stale,
    )


def test_resolve_assignee_picks_first_active_manager() -> None:
    subject = _user("sub-1", dtuid="s1")
    mgr0 = _user("mgr-0", dtuid="m0", status=USER_STATUS_DEPARTED)
    mgr1 = _user("mgr-1", dtuid="m1")
    _ = mgr0
    _chain(subject, ["m0", "m1"])
    res = resolve_assignee(subject)
    assert res.user is not None
    assert res.user.authentik_user_id == "mgr-1"
    assert res.state == ASSIGNEE_STATE_MANAGER
    assert res.level == 1
    assert res.degraded is False


def test_resolve_assignee_stale_falls_to_pool() -> None:
    subject = _user("sub-2", dtuid="s2")
    _ = _user("mgr-x", dtuid="mx")
    _chain(subject, ["mx"], stale=True)
    res = resolve_assignee(subject)
    assert res.user is None
    assert res.state == ASSIGNEE_STATE_SUPERUSER_POOL
    assert res.degraded is True


def test_resolve_assignee_skips_local_admin() -> None:
    subject = _user("sub-3", dtuid="s3")
    _ = UserMirror.objects.create(
        authentik_user_id=f"{LOCAL_ADMIN_SUBJECT_PREFIX}break",
        name="local",
        status=USER_STATUS_ACTIVE,
        dingtalk_source_slug=SOURCE,
        dingtalk_corp_id=CORP,
        dingtalk_userid="admin-dt",
    )
    real = _user("mgr-real", dtuid="mreal")
    _chain(subject, ["admin-dt", "mreal"])
    res = resolve_assignee(subject)
    assert res.user is not None
    assert res.user.pk == real.pk
    assert res.level == 1


def test_resolve_assignee_chain_exhausted_to_pool() -> None:
    subject = _user("sub-4", dtuid="s4")
    _ = _user("mgr-d", dtuid="md", status=USER_STATUS_DEPARTED)
    _chain(subject, ["md"])
    res = resolve_assignee(subject)
    assert res.user is None
    assert res.state == ASSIGNEE_STATE_SUPERUSER_POOL
    assert res.level == 1
    assert res.degraded is False


def test_apply_assignee_writes_fields_and_deadline() -> None:
    subject = _user("sub-5", dtuid="s5")
    mgr = _user("mgr-5", dtuid="m5")
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        created_by="admin",
    )
    res = resolve_assignee(subject)  # no chain → pool
    assert res.degraded is True
    _chain(subject, ["m5"])
    res = resolve_assignee(subject)
    apply_assignee(task, res, actor_id="admin")
    task.refresh_from_db()
    assert task.assignee_id == mgr.pk
    assert task.assignee_state == ASSIGNEE_STATE_MANAGER
    assert task.escalation_deadline is not None
