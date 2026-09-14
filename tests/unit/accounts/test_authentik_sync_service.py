from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.core.cache import cache
from django.test import TestCase

from easyauth.accounts.models import (
    USER_STATUS_ACTIVE,
    DingTalkDepartmentMirror,
    DingTalkUserMirror,
    UserMirror,
)
from easyauth.accounts.services import AuthentikSyncService
from easyauth.applications.models import App, AppScope, AuthorizationGroup, Permission
from easyauth.grants import department_reconcile
from easyauth.grants.department_reconcile import DEPARTMENT_GRANT_RECONCILE_LOCK_KEY
from easyauth.grants.models import (
    AccessGrant,
    AccessGrantGroup,
    DepartmentGrantPolicy,
    DepartmentGrantPolicyGroup,
    DepartmentGrantPolicyPermission,
)
from easyauth.grants.query import resolve_user_permissions
from easyauth.outbox.models import OutboxEvent

if TYPE_CHECKING:
    from easyauth.integrations.authentik.payloads import AuthentikPayloadInput

pytestmark = pytest.mark.django_db

_SOURCE = "dingtalk"
_CORP = "corp"
_DEPT = "990739069"
_USER_ID = "ding-chen-ning"
_SUBJECT = "fdac7e94-a7ab-4311-9b57-436f3a35f3cb"
_GROUP_KEY = "easycustoms-customs-viewer"


def _payload(*, subject: str, user_id: str, active: bool = True) -> AuthentikPayloadInput:
    return {
        "user": {
            "uid": subject,
            "name": "陈柠",
            "email": "chenning@example.test",
            "attributes": {
                "department": "外贸部",
                "dingtalk": {
                    "source_slug": _SOURCE,
                    "corp_id": _CORP,
                    "user_id": user_id,
                },
            },
        },
        "is_active": active,
    }


def _department_catalog() -> tuple[App, AuthorizationGroup]:
    app = App.objects.create(app_key="easycustoms", name="EasyCustoms")
    AppScope.objects.get_or_create(app=app, key="GLOBAL", defaults={"name": "全局"})
    group = AuthorizationGroup.objects.create(app=app, key=_GROUP_KEY, name="报关只读", kind="role")
    permission = Permission.objects.create(
        app=app, key="customs.read", name="读取", supported_scopes=["GLOBAL"]
    )
    DingTalkDepartmentMirror.objects.create(
        source_slug=_SOURCE, corp_id=_CORP, dept_id=_DEPT, parent_id="", name="外贸部"
    )
    policy = DepartmentGrantPolicy.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP,
        dept_id=_DEPT,
        app=app,
        grant_type="permanent",
        reason="部门策略",
        created_by_type="admin",
        created_by_id="admin",
        updated_by_type="admin",
        updated_by_id="admin",
    )
    DepartmentGrantPolicyGroup.objects.create(policy=policy, authorization_group=group)
    DepartmentGrantPolicyPermission.objects.create(
        policy=policy, permission=permission, scope_key="GLOBAL"
    )
    return app, group


def _directory_mirror(user_id: str = _USER_ID) -> DingTalkUserMirror:
    return DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP,
        user_id=user_id,
        status="active",
        department_ids=[_DEPT],
    )


def _user_sync_events() -> int:
    return OutboxEvent.objects.filter(
        event_key__startswith="department-grant-reconcile:user-sync:"
    ).count()


def test_sync_payload_first_seen_directory_user_materialises_department_grant() -> None:
    app, group = _department_catalog()
    _directory_mirror()

    created = AuthentikSyncService.sync_payload(_payload(subject=_SUBJECT, user_id=_USER_ID))

    assert created.created is True
    grant = AccessGrant.objects.get(user=created.user, app=app, is_current=True)
    assert AccessGrantGroup.objects.get(grant=grant).source == "department"
    snapshot = resolve_user_permissions(user=_SUBJECT, app=app)
    assert snapshot.grant_version == grant.version
    assert [item.key for item in snapshot.groups] == [group.key]
    assert _user_sync_events() == 0


def test_sync_payload_does_not_touch_other_directory_users() -> None:
    app, _group = _department_catalog()
    _directory_mirror()
    other = UserMirror.objects.create(
        authentik_user_id="other-directory-user",
        status="active",
        dingtalk_source_slug=_SOURCE,
        dingtalk_corp_id=_CORP,
        dingtalk_userid="other-ding",
    )
    DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP,
        user_id="other-ding",
        status="active",
        department_ids=[_DEPT],
    )

    created = AuthentikSyncService.sync_payload(_payload(subject=_SUBJECT, user_id=_USER_ID))

    assert AccessGrant.objects.filter(user=created.user, app=app).exists()
    assert not AccessGrant.objects.filter(user=other).exists()


def test_sync_payload_skips_non_directory_and_inactive_users() -> None:
    app, _group = _department_catalog()
    _directory_mirror()
    local_payload: AuthentikPayloadInput = {
        "user": {"uid": "local-user", "name": "本地用户", "email": "local@example.test"},
        "is_active": True,
    }

    local = AuthentikSyncService.sync_payload(local_payload)
    inactive = AuthentikSyncService.sync_payload(
        _payload(subject="inactive-user", user_id=_USER_ID, active=False)
    )

    assert local.created is True
    assert inactive.created is True
    assert not AccessGrant.objects.filter(user=local.user, app=app).exists()
    assert not AccessGrant.objects.filter(user=inactive.user, app=app).exists()
    assert _user_sync_events() == 0


def test_sync_payload_existing_active_user_does_not_reconcile_again() -> None:
    _department_catalog()
    _directory_mirror()
    first = AuthentikSyncService.sync_payload(_payload(subject=_SUBJECT, user_id=_USER_ID))
    grant_count = AccessGrant.objects.count()

    updated = AuthentikSyncService.sync_payload(_payload(subject=_SUBJECT, user_id=_USER_ID))

    assert first.created is True
    assert updated.created is False
    assert AccessGrant.objects.count() == grant_count
    assert _user_sync_events() == 0


def test_sync_payload_lock_busy_creates_user_and_schedules_full_pass(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _department_catalog()
    _directory_mirror()
    monkeypatch.setattr(department_reconcile, "DEPARTMENT_GRANT_USER_LOCK_WAIT_SECONDS", 0)
    assert cache.add(DEPARTMENT_GRANT_RECONCILE_LOCK_KEY, "1", timeout=30)
    try:
        with (
            caplog.at_level("WARNING", logger="easyauth.accounts.services"),
            TestCase.captureOnCommitCallbacks(execute=True),
        ):
            created = AuthentikSyncService.sync_payload(
                _payload(subject=_SUBJECT, user_id=_USER_ID)
            )
        assert created.created is True
        assert UserMirror.objects.filter(authentik_user_id=_SUBJECT).exists()
        assert not AccessGrant.objects.exists()
        assert _user_sync_events() == 1
        assert any("已推迟到全量" in record.message for record in caplog.records)
    finally:
        cache.delete(DEPARTMENT_GRANT_RECONCILE_LOCK_KEY)


def test_sync_payload_reconcile_failure_still_creates_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _department_catalog()
    _directory_mirror()

    def boom(_user: UserMirror, **_kwargs: object) -> None:
        message = "测试对账失败"
        raise RuntimeError(message)

    monkeypatch.setattr("easyauth.accounts.services.reconcile_department_grants_for_user", boom)
    with TestCase.captureOnCommitCallbacks(execute=True):
        created = AuthentikSyncService.sync_payload(_payload(subject=_SUBJECT, user_id=_USER_ID))
    assert created.created is True
    assert UserMirror.objects.filter(authentik_user_id=_SUBJECT).exists()
    assert not AccessGrant.objects.exists()
    assert _user_sync_events() == 1


def test_apply_directory_status_reactivation_does_not_run_scoped_reconcile() -> None:
    app, _group = _department_catalog()
    _directory_mirror()
    user = UserMirror.objects.create(
        authentik_user_id=_SUBJECT,
        status="departed",
        dingtalk_source_slug=_SOURCE,
        dingtalk_corp_id=_CORP,
        dingtalk_userid=_USER_ID,
    )

    result = AuthentikSyncService.apply_directory_status(user, USER_STATUS_ACTIVE)

    assert result.created is False
    result.user.refresh_from_db()
    assert result.user.status == USER_STATUS_ACTIVE
    # 目录同步整轮事务结束后才入队全量对账, 此处不得持锁物化。
    assert not AccessGrant.objects.filter(user=result.user, app=app).exists()
    assert _user_sync_events() == 0
