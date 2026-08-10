"""租约并发与 CAS — 必须在真 PostgreSQL 上跑(01 §10)。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import connection, transaction
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    HANDOVER_CAPABILITY_DECLARED,
    App,
)
from easyauth.lifecycle.errors import HandoverConflictError
from easyauth.lifecycle.lease import (
    HANDOVER_EXECUTION_IN_FLIGHT,
    allocate_fence,
    cas_release,
    preempt_expired_lease,
    renew_lease,
    take_lease,
)
from easyauth.lifecycle.models import (
    ACTION_STATUS_PREVIEWED,
    HANDOVER_KIND_OFFBOARD,
    HANDOVER_KIND_REASSIGN,
    LEASE_RENEW_INTERVAL,
    LEASE_TTL,
    HandoverAppAction,
    HandoverExecutionLease,
    HandoverTask,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="租约条件唯一约束与并发必须在 PostgreSQL lane 验证。",
    ),
]


def _setup() -> tuple[HandoverAppAction, HandoverAppAction]:
    assert connection.vendor == "postgresql"
    subject = UserMirror.objects.create(authentik_user_id="lease-sub", name="lease")
    app = App.objects.create(
        app_key="lease-app",
        name="lease",
        handover_capability=HANDOVER_CAPABILITY_DECLARED,
        handover_asset_types=[{"type": "x", "label": "X", "detail_supported": False, "releasable": False}],
    )
    task1 = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        created_by="admin",
    )
    # reassign 可与 offboard 并存; 两 action 同 subject/app 互斥测租约。
    task2 = HandoverTask.objects.create(
        kind=HANDOVER_KIND_REASSIGN,
        subject_user=subject,
        created_by="admin",
        reason="lease concurrency fixture",
    )
    action1 = HandoverAppAction.objects.create(
        task=task1,
        app=app,
        status=ACTION_STATUS_PREVIEWED,
        generation=1,
        snapshot_token="tok-1",
    )
    action2 = HandoverAppAction.objects.create(
        task=task2,
        app=app,
        status=ACTION_STATUS_PREVIEWED,
        generation=1,
        snapshot_token="tok-2",
    )
    return action1, action2


def test_lease_ttl_constants() -> None:
    assert LEASE_TTL == timedelta(minutes=5)
    assert LEASE_RENEW_INTERVAL == LEASE_TTL / 3


def test_concurrent_take_lease_only_one_wins() -> None:
    action1, action2 = _setup()
    with transaction.atomic():
        h1 = take_lease(action=action1, owner="w1", batch_seq=1)
    with pytest.raises(HandoverConflictError) as exc:
        with transaction.atomic():
            _ = take_lease(action=action2, owner="w2", batch_seq=1)
    assert str(exc.value) == HANDOVER_EXECUTION_IN_FLIGHT
    assert HandoverExecutionLease.objects.filter(released_at__isnull=True).count() == 1
    assert cas_release(h1)


def test_renew_requires_owner_fence_and_not_expired() -> None:
    action1, _action2 = _setup()
    with transaction.atomic():
        handle = take_lease(action=action1, owner="renewer", batch_seq=1)
    assert renew_lease(handle)
    # 错误 fence
    bad = handle.__class__(
        lease_id=handle.lease_id,
        owner=handle.owner,
        fence=handle.fence + 99,
        expires_at=handle.expires_at,
    )
    assert not renew_lease(bad)
    # 过期后原 owner 不可续约
    HandoverExecutionLease.objects.filter(pk=handle.lease_id).update(
        lease_expires_at=timezone.now() - timedelta(seconds=1),
    )
    assert not renew_lease(handle)


def test_preempt_expired_then_release() -> None:
    action1, _action2 = _setup()
    with transaction.atomic():
        handle = take_lease(action=action1, owner="old-worker", batch_seq=1)
    lease = HandoverExecutionLease.objects.get(pk=handle.lease_id)
    lease.lease_expires_at = timezone.now() - timedelta(seconds=1)
    lease.save(update_fields=["lease_expires_at"])
    with transaction.atomic():
        new_handle = preempt_expired_lease(lease, new_owner="recoverer")
    assert new_handle is not None
    assert new_handle.owner == "recoverer"
    assert new_handle.fence > handle.fence
    # 旧 handle CAS 失败
    assert not cas_release(handle)
    assert cas_release(new_handle)


def test_fence_allocate_monotonic() -> None:
    action1, _ = _setup()
    subject = action1.task.subject_user
    app = action1.app
    with transaction.atomic():
        f1 = allocate_fence(subject_user=subject, app=app)
        f2 = allocate_fence(subject_user=subject, app=app)
    assert f2 == f1 + 1
