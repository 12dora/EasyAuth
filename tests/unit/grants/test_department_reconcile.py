from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from celery.exceptions import Retry
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from easyauth.accounts.department_tree import DepartmentTreeCycleError
from easyauth.accounts.models import DingTalkDepartmentMirror, DingTalkUserMirror, UserMirror
from easyauth.applications.models import App, AppScope, AuthorizationGroup, Permission
from easyauth.audit.models import AuditLog
from easyauth.grants import department_reconcile
from easyauth.grants.department_reconcile import (
    DEPARTMENT_GRANT_RECONCILE_LOCK_KEY,
    DEPARTMENT_GRANT_RECONCILE_LOCK_TTL_SECONDS,
    DepartmentGrantReconcileBusyError,
    DepartmentGrantReconcileError,
    reconcile_department_grants,
    schedule_department_grant_reconcile,
)
from easyauth.grants.inputs import AuthorizationGroupGrantInput, ScopedDirectGrantInput
from easyauth.grants.models import (
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
    DepartmentGrantPolicy,
    DepartmentGrantPolicyGroup,
    DepartmentGrantPolicyPermission,
)
from easyauth.grants.services import GrantService
from easyauth.outbox.models import OutboxEvent
from easyauth.tasks.grants import reconcile_department_grants_task

if TYPE_CHECKING:
    from collections.abc import Iterable

pytestmark = pytest.mark.django_db


@dataclass(frozen=True)
class Catalog:
    app: App
    group: AuthorizationGroup
    permission: Permission


@pytest.fixture
def catalog() -> Catalog:
    app = App.objects.create(app_key="department-app", name="组织授权")
    AppScope.objects.get_or_create(app=app, key="GLOBAL", defaults={"name": "全局"})
    group = AuthorizationGroup.objects.create(app=app, key="reader", name="读取", kind="role")
    permission = Permission.objects.create(
        app=app, key="read", name="读取", supported_scopes=["GLOBAL"]
    )
    for dept_id, parent_id in [("1", ""), ("2", "1"), ("3", "2"), ("4", "1")]:
        DingTalkDepartmentMirror.objects.create(
            source_slug="dingtalk",
            corp_id="corp",
            dept_id=dept_id,
            parent_id=parent_id,
            name=dept_id,
        )
    return Catalog(app, group, permission)


def _user(key: str = "user") -> tuple[UserMirror, DingTalkUserMirror]:
    user = UserMirror.objects.create(
        authentik_user_id=key,
        status="active",
        dingtalk_source_slug="dingtalk",
        dingtalk_corp_id="corp",
        dingtalk_userid=key,
    )
    mirror = DingTalkUserMirror.objects.create(
        source_slug="dingtalk", corp_id="corp", user_id=key, status="active", department_ids=["3"]
    )
    return user, mirror


def _policy(
    catalog: Catalog, *, dept_id: str = "1", expires_at: datetime | None = None
) -> DepartmentGrantPolicy:
    policy = DepartmentGrantPolicy.objects.create(
        source_slug="dingtalk",
        corp_id="corp",
        dept_id=dept_id,
        app=catalog.app,
        grant_type="permanent" if expires_at is None else "timed",
        expires_at=expires_at,
        reason="部门策略",
        created_by_type="admin",
        created_by_id="admin",
        updated_by_type="admin",
        updated_by_id="admin",
    )
    DepartmentGrantPolicyGroup.objects.create(policy=policy, authorization_group=catalog.group)
    DepartmentGrantPolicyPermission.objects.create(
        policy=policy, permission=catalog.permission, scope_key="GLOBAL"
    )
    return policy


def _inputs(
    catalog: Catalog, policy: DepartmentGrantPolicy
) -> tuple[tuple[AuthorizationGroupGrantInput, ...], tuple[ScopedDirectGrantInput, ...]]:
    return (
        (AuthorizationGroupGrantInput(catalog.group, policy.expires_at, "department", policy.id),),
        (
            ScopedDirectGrantInput(
                catalog.permission, "GLOBAL", policy.expires_at, "department", policy.id
            ),
        ),
    )


def test_service_create_noop_change_remove_and_recreate(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, _mirror = _user()
    policy = _policy(catalog)
    groups, direct = _inputs(catalog, policy)
    notifications: list[int] = []
    monkeypatch.setattr(
        "easyauth.grants.services.notify_grant_mutation",
        lambda grant: notifications.append(grant.version),
    )
    assert (
        GrantService.sync_department_memberships(
            user=user, app=catalog.app, authorization_groups=(), direct_grants=()
        )
        is None
    )
    grant = GrantService.sync_department_memberships(
        user=user, app=catalog.app, authorization_groups=groups, direct_grants=direct
    )
    assert grant is not None
    assert grant.version == 1
    with CaptureQueriesContext(connection) as captured:
        same = GrantService.sync_department_memberships(
            user=user, app=catalog.app, authorization_groups=groups, direct_grants=direct
        )
    assert same is not None
    assert same.version == 1
    _assert_no_writes(captured)
    grant = GrantService.sync_department_memberships(
        user=user, app=catalog.app, authorization_groups=groups, direct_grants=()
    )
    assert grant is not None
    assert grant.version == 2
    grant = GrantService.sync_department_memberships(
        user=user, app=catalog.app, authorization_groups=(), direct_grants=()
    )
    assert grant is not None
    assert grant.status == "revoked"
    assert grant.version == 3
    assert not AccessGrantGroup.objects.filter(grant=grant).exists()
    assert list(AuditLog.objects.order_by("id").values_list("event_type", flat=True)) == [
        "grant_created",
        "grant_changed",
        "grant_revoked",
    ]
    audit = AuditLog.objects.get(event_type="grant_created")
    assert audit.metadata["source"] == "department"
    assert audit.metadata["policy_ids"] == [policy.id]
    assert (
        AuditLog.objects.get(event_type="grant_revoked").metadata["reason"]
        == "department policy removed"
    )
    assert notifications == [1, 2, 3]
    result = reconcile_department_grants()
    assert result.grants_created == 1
    assert AccessGrant.objects.get(user=user, is_current=True).version == 4


def _assert_no_writes(captured: CaptureQueriesContext) -> None:
    assert not [
        row["sql"]
        for row in captured.captured_queries
        if row["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    ]


def test_company_policy_grandchild_and_noop_pass_are_batched(catalog: Catalog) -> None:
    _policy(catalog)
    _user()
    first = reconcile_department_grants()
    assert first.users_considered == 1
    assert first.grants_created == 1
    audit_count = AuditLog.objects.count()
    with CaptureQueriesContext(connection) as small:
        result = reconcile_department_grants()
    assert result.unchanged == 1
    assert result.grants_changed == 0
    _assert_no_writes(small)
    assert AuditLog.objects.count() == audit_count
    for index in range(6):
        _user(f"user-{index}")
    reconcile_department_grants()
    with CaptureQueriesContext(connection) as large:
        result = reconcile_department_grants()
    assert result.unchanged == 7
    assert len(large) == len(small)
    _assert_no_writes(large)


def test_moving_department_swaps_memberships_in_one_version(catalog: Catalog) -> None:
    user, mirror = _user()
    first_policy = _policy(catalog, dept_id="2")
    other_group = AuthorizationGroup.objects.create(
        app=catalog.app, key="writer", name="写入", kind="role"
    )
    second_policy = _policy(Catalog(catalog.app, other_group, catalog.permission), dept_id="4")
    reconcile_department_grants()
    assert AccessGrantGroup.objects.get(grant__user=user).department_policy == first_policy
    mirror.department_ids = ["4"]
    mirror.save(update_fields=["department_ids"])
    result = reconcile_department_grants()
    assert result.grants_changed == 1
    grant = AccessGrant.objects.get(user=user, is_current=True)
    assert grant.version == 2
    assert AccessGrantGroup.objects.get(grant=grant).department_policy == second_policy
    assert AccessGrantGroup.objects.get(grant=grant).authorization_group == other_group
    assert AuditLog.objects.filter(event_type="grant_changed").count() == 1


@pytest.mark.parametrize(
    "ineligible", ["tombstone", "departed", "disabled", "missing", "unbound", "outside"]
)
@pytest.mark.parametrize("personal", [False, True])
def test_ineligible_users_lose_only_department_rows(
    catalog: Catalog, ineligible: str, *, personal: bool
) -> None:
    user, mirror = _user()
    _policy(catalog, dept_id="2")
    reconcile_department_grants()
    grant = AccessGrant.objects.get(user=user, is_current=True)
    if personal:
        AccessGrantPermission.objects.create(
            grant=grant, permission=catalog.permission, source="user"
        )
    if ineligible == "tombstone":
        mirror.is_tombstone = True
        mirror.save()
    elif ineligible == "departed":
        mirror.status = "departed"
        mirror.save()
    elif ineligible == "disabled":
        user.status = "disabled"
        user.save()
    elif ineligible == "missing":
        mirror.delete()
    elif ineligible == "unbound":
        user.dingtalk_source_slug = user.dingtalk_corp_id = user.dingtalk_userid = ""
        user.save()
    else:
        mirror.department_ids = ["4"]
        mirror.save()
    result = reconcile_department_grants()
    grant.refresh_from_db()
    assert grant.version == 2
    assert not AccessGrantGroup.objects.filter(grant=grant, source="department").exists()
    assert not AccessGrantPermission.objects.filter(grant=grant, source="department").exists()
    assert grant.is_current is personal
    assert result.grants_changed == int(personal)
    assert result.grants_revoked == int(not personal)
    assert AccessGrantPermission.objects.filter(grant=grant, source="user").exists() is personal


@pytest.mark.parametrize("permanent", [False, True])
def test_overlapping_policies_merge_expiry_and_ignore_expired(
    catalog: Catalog, *, permanent: bool
) -> None:
    _user()
    now = timezone.now()
    _policy(catalog, expires_at=now - timedelta(days=1))
    short = _policy(catalog, expires_at=now + timedelta(days=1))
    long = _policy(catalog, dept_id="2", expires_at=None if permanent else now + timedelta(days=3))
    reconcile_department_grants(now=now)
    assert AccessGrantGroup.objects.get().department_policy == long
    assert AccessGrantPermission.objects.get().expires_at == long.expires_at
    long.delete()
    result = reconcile_department_grants(now=now)
    assert result.grants_changed == 1
    assert AccessGrantGroup.objects.get().department_policy == short
    assert AccessGrantPermission.objects.get().expires_at == short.expires_at
    result = reconcile_department_grants(now=now + timedelta(days=2))
    assert result.grants_revoked == 1


def test_deleted_policy_with_null_provenance_is_removed(catalog: Catalog) -> None:
    _user()
    policy = _policy(catalog)
    reconcile_department_grants()
    policy.delete()
    assert AccessGrantGroup.objects.get().department_policy is None
    result = reconcile_department_grants()
    assert result.grants_revoked == 1


def test_cycle_anywhere_aborts_before_writes(catalog: Catalog) -> None:
    _user()
    _policy(catalog)
    for dept, parent in [("8", "9"), ("9", "8")]:
        DingTalkDepartmentMirror.objects.create(
            source_slug="dingtalk", corp_id="corp", dept_id=dept, parent_id=parent, name=dept
        )
    with pytest.raises(DepartmentTreeCycleError):
        reconcile_department_grants()
    assert not AccessGrant.objects.exists()
    assert not AuditLog.objects.exists()


def test_pair_failure_rolls_back_only_failed_pair_and_raises_summary(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad, _mirror = _user("bad")
    good, _mirror = _user("good")
    _policy(catalog)
    original = GrantService.sync_department_memberships

    def fail_after_write(
        *,
        user: UserMirror,
        app: App,
        authorization_groups: Iterable[AuthorizationGroupGrantInput],
        direct_grants: Iterable[ScopedDirectGrantInput],
    ) -> AccessGrant | None:
        grant = original(
            user=user,
            app=app,
            authorization_groups=authorization_groups,
            direct_grants=direct_grants,
        )
        if user == bad:
            message = "测试事务回滚"
            raise RuntimeError(message)
        return grant

    monkeypatch.setattr(GrantService, "sync_department_memberships", fail_after_write)
    with pytest.raises(DepartmentGrantReconcileError) as failure:
        reconcile_department_grants()
    assert failure.value.result.grants_created == 1
    assert len(failure.value.failures) == 1
    assert not AccessGrant.objects.filter(user=bad).exists()
    assert AccessGrant.objects.filter(user=good).exists()
    assert AuditLog.objects.count() == 1


def test_identical_expiry_uses_lowest_policy_id_and_policy_change_bumps_version(
    catalog: Catalog,
) -> None:
    user, _mirror = _user()
    first = _policy(catalog, dept_id="3")
    second = _policy(catalog, dept_id="1")
    reconcile_department_grants()
    assert AccessGrantGroup.objects.get().department_policy == first
    first.delete()
    result = reconcile_department_grants()
    assert result.grants_changed == 1
    assert AccessGrant.objects.get(user=user).version == 2
    assert AccessGrantGroup.objects.get().department_policy == second


def test_policy_for_missing_department_does_not_match_stale_user_membership(
    catalog: Catalog,
) -> None:
    _user()
    _policy(catalog)
    DingTalkDepartmentMirror.objects.all().delete()
    result = reconcile_department_grants()
    assert result.unchanged == 1
    assert not AccessGrant.objects.exists()


def test_department_task_registration_and_result(catalog: Catalog) -> None:
    _user()
    _policy(catalog)
    assert "easyauth.tasks.grants" in settings.CELERY_IMPORTS
    assert (
        settings.CELERY_BEAT_SCHEDULE["department-grant-reconcile"]["task"]
        == "easyauth.grants.reconcile_department_grants"
    )
    assert reconcile_department_grants_task.acks_late is True
    assert reconcile_department_grants_task.max_retries is None
    assert reconcile_department_grants_task.retry_kwargs["max_retries"] == 3
    assert reconcile_department_grants_task.time_limit < DEPARTMENT_GRANT_RECONCILE_LOCK_TTL_SECONDS
    assert reconcile_department_grants_task.retry_backoff == 30
    assert DepartmentTreeCycleError not in reconcile_department_grants_task.autoretry_for
    assert reconcile_department_grants_task.run() == {
        "users_considered": 1,
        "grants_created": 1,
        "grants_changed": 0,
        "grants_revoked": 0,
        "unchanged": 0,
    }


def test_eligibility_uses_complete_directory_binding(catalog: Catalog) -> None:
    _policy(catalog)
    eligible, _mirror = _user("shared-id")
    outside = UserMirror.objects.create(
        authentik_user_id="outside-corp",
        status="active",
        dingtalk_source_slug="dingtalk",
        dingtalk_corp_id="other-corp",
        dingtalk_userid="shared-id",
    )
    missing = UserMirror.objects.create(
        authentik_user_id="missing-binding",
        status="active",
        dingtalk_source_slug="dingtalk",
        dingtalk_corp_id="corp",
        dingtalk_userid="missing",
    )
    result = reconcile_department_grants()
    assert result.users_considered == 1
    assert AccessGrant.objects.get().user == eligible
    assert not AccessGrant.objects.filter(user__in=[outside, missing]).exists()


def test_scheduler_buckets_at_commit_after_earlier_event_was_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = timezone.now().replace(microsecond=0)
    monkeypatch.setattr(timezone, "now", lambda: now)
    with TestCase.captureOnCommitCallbacks(execute=False) as callbacks:
        schedule_department_grant_reconcile(trigger="policy")
        schedule_department_grant_reconcile(trigger="policy")
    assert not OutboxEvent.objects.exists()
    callbacks[0]()
    event = OutboxEvent.objects.get()
    assert event.available_at > now + timedelta(seconds=1)
    event.status = "published"
    event.published_at = now
    event.save(update_fields=["status", "published_at"])
    now += timedelta(seconds=1)
    callbacks[1]()
    pending = OutboxEvent.objects.get(status="pending")
    assert pending.pk != event.pk
    assert pending.event_key.endswith(f":{int(now.timestamp())}")
    with TestCase.captureOnCommitCallbacks(execute=True):
        schedule_department_grant_reconcile(trigger="policy")
    assert OutboxEvent.objects.count() == 2


def test_overlapping_pass_retries_then_applies_new_policy(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    _user()
    policy = _policy(catalog)
    expiry = timezone.now() + timedelta(days=1)
    original = department_reconcile._desired_by_pair  # noqa: SLF001 - 在读取旧快照后交错触发第二批次。

    def change_policy_after_snapshot(*args: object, **kwargs: object) -> object:
        desired = original(*args, **kwargs)
        policy.grant_type = "timed"
        policy.expires_at = expiry
        policy.save(update_fields=["grant_type", "expires_at"])
        with CaptureQueriesContext(connection) as captured:
            with pytest.raises(DepartmentGrantReconcileBusyError):
                reconcile_department_grants()
            # 多次锁竞争后仍需重试; 使用真实 Celery retry, 隔离 broker 发送。
            reconcile_department_grants_task.push_request(
                retries=10, called_directly=False, is_eager=True
            )
            try:
                with pytest.raises(Retry) as retried:
                    reconcile_department_grants_task.run()
            finally:
                reconcile_department_grants_task.pop_request()
        assert retried.value.when == 5
        assert not captured.captured_queries
        assert cache.get(DEPARTMENT_GRANT_RECONCILE_LOCK_KEY) is not None
        return desired

    with monkeypatch.context() as patch:
        patch.setattr(department_reconcile, "_desired_by_pair", change_policy_after_snapshot)
        assert reconcile_department_grants().grants_created == 1
    assert cache.get(DEPARTMENT_GRANT_RECONCILE_LOCK_KEY) is None
    assert AccessGrantPermission.objects.get().expires_at is None
    assert reconcile_department_grants_task.run()["grants_changed"] == 1
    assert AccessGrantPermission.objects.get().expires_at == expiry
    assert AccessGrant.objects.get().version == 2
    assert cache.get(DEPARTMENT_GRANT_RECONCILE_LOCK_KEY) is None


def test_failed_pass_releases_lock(catalog: Catalog) -> None:
    _user()
    _policy(catalog)
    dept = DingTalkDepartmentMirror.objects.get(dept_id="1")
    dept.parent_id = "3"
    dept.save(update_fields=["parent_id"])
    with pytest.raises(DepartmentTreeCycleError):
        reconcile_department_grants()
    assert cache.get(DEPARTMENT_GRANT_RECONCILE_LOCK_KEY) is None
    dept.parent_id = ""
    dept.save(update_fields=["parent_id"])
    assert reconcile_department_grants().grants_created == 1
