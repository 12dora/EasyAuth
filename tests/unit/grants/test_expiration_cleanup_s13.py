from __future__ import annotations

from datetime import timedelta
from typing import Final

import pytest
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    GRANT_STATUS_EXPIRED,
    GRANT_STATUS_REVOKED,
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    AccessGrant,
)
from easyauth.grants.services import GrantExpirationInput, GrantService
from easyauth.tasks.grants import GRANT_EXPIRATION_REASON, cleanup_expired_grants

pytestmark = pytest.mark.django_db

INITIAL_VERSION: Final = 1
EXPIRED_VERSION: Final = 2
EXPECTED_EXPIRED_GRANTS: Final = 2


def test_s13_cleanup_expired_grants_expires_only_due_current_active_timed_grants_once() -> None:
    # Given: 当前有到期、未到期、永久、以及已经撤销的授权。
    now = timezone.now()
    due_user = UserMirror.objects.create(authentik_user_id="s13-cleanup-due-user")
    second_due_user = UserMirror.objects.create(authentik_user_id="s13-cleanup-second-due-user")
    future_user = UserMirror.objects.create(authentik_user_id="s13-cleanup-future-user")
    permanent_user = UserMirror.objects.create(authentik_user_id="s13-cleanup-permanent-user")
    revoked_user = UserMirror.objects.create(authentik_user_id="s13-cleanup-revoked-user")
    due_app = App.objects.create(app_key="s13-cleanup-due-app", name="S13 Cleanup Due")
    second_due_app = App.objects.create(
        app_key="s13-cleanup-second-due-app",
        name="S13 Cleanup Second Due",
    )
    future_app = App.objects.create(app_key="s13-cleanup-future-app", name="S13 Cleanup Future")
    permanent_app = App.objects.create(
        app_key="s13-cleanup-permanent-app",
        name="S13 Cleanup Permanent",
    )
    revoked_app = App.objects.create(
        app_key="s13-cleanup-revoked-app",
        name="S13 Cleanup Revoked",
    )
    due_grant = AccessGrant.objects.create(
        user=due_user,
        app=due_app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=now - timedelta(seconds=1),
    )
    second_due_grant = AccessGrant.objects.create(
        user=second_due_user,
        app=second_due_app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=now,
    )
    future_grant = AccessGrant.objects.create(
        user=future_user,
        app=future_app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=now + timedelta(minutes=1),
    )
    permanent_grant = AccessGrant.objects.create(
        user=permanent_user,
        app=permanent_app,
        grant_type=GRANT_TYPE_PERMANENT,
    )
    revoked_grant = AccessGrant.objects.create(
        user=revoked_user,
        app=revoked_app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=now - timedelta(minutes=1),
        status=GRANT_STATUS_REVOKED,
        is_current=False,
    )

    # When: 定时清理重复运行两次。
    first = cleanup_expired_grants(now=now)
    repeated = cleanup_expired_grants(now=now)

    # Then: 只有到期的当前 active timed grants 被过期, 且重复执行保持幂等。
    due_grant.refresh_from_db()
    second_due_grant.refresh_from_db()
    future_grant.refresh_from_db()
    permanent_grant.refresh_from_db()
    revoked_grant.refresh_from_db()
    assert first.expired_count == EXPECTED_EXPIRED_GRANTS
    assert [grant.app.app_key for grant in first.expired_grants] == [
        "s13-cleanup-due-app",
        "s13-cleanup-second-due-app",
    ]
    assert repeated.expired_count == 0
    assert due_grant.status == GRANT_STATUS_EXPIRED
    assert second_due_grant.status == GRANT_STATUS_EXPIRED
    assert due_grant.version == EXPIRED_VERSION
    assert second_due_grant.version == EXPIRED_VERSION
    assert due_grant.is_current is False
    assert second_due_grant.is_current is False
    assert future_grant.status == GRANT_STATUS_ACTIVE
    assert permanent_grant.status == GRANT_STATUS_ACTIVE
    assert revoked_grant.status == GRANT_STATUS_REVOKED
    assert future_grant.version == INITIAL_VERSION
    assert permanent_grant.version == INITIAL_VERSION
    assert revoked_grant.version == INITIAL_VERSION
    audit_logs = AuditLog.objects.filter(event_type="grant_expired")
    assert audit_logs.count() == EXPECTED_EXPIRED_GRANTS
    for audit_log in audit_logs:
        assert audit_log.actor_type == "system"
        assert audit_log.actor_id == "grant-expiration-cleanup"
        assert audit_log.metadata["reason"] == GRANT_EXPIRATION_REASON
        assert audit_log.metadata["version"] == EXPIRED_VERSION


def test_s13_cleanup_expired_grants_skips_candidate_consumed_by_concurrent_revoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 清理任务选中到期 grant 后, 另一个撤权路径先消费了该 grant。
    now = timezone.now()
    user = UserMirror.objects.create(authentik_user_id="s13-cleanup-concurrent-user")
    app = App.objects.create(app_key="s13-cleanup-concurrent-app", name="S13 Concurrent")
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=now - timedelta(seconds=1),
    )
    original_expire_grant = GrantService.expire_grant

    def revoke_before_expire(input_data: GrantExpirationInput) -> AccessGrant | None:
        _ = GrantService.revoke_grant(
            user=input_data.user,
            app=input_data.app,
            actor_type="system",
            actor_id="concurrent-revoker",
        )
        return original_expire_grant(input_data)

    monkeypatch.setattr(GrantService, "expire_grant", staticmethod(revoke_before_expire))

    # When: 清理任务处理这个已经被并发撤权消费的候选 grant。
    result = cleanup_expired_grants(now=now)

    # Then: 清理任务跳过该候选, 不写过期审计也不再次递增 version。
    grant.refresh_from_db()
    assert result.expired_count == 0
    assert grant.status == GRANT_STATUS_REVOKED
    assert grant.version == EXPIRED_VERSION
    assert AuditLog.objects.filter(event_type="grant_expired").count() == 0


def test_s13_cleanup_expired_grants_skips_candidate_extended_before_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 清理任务选中到期 grant 后, 授权在写入锁内复核前被延长。
    now = timezone.now()
    user = UserMirror.objects.create(authentik_user_id="s13-cleanup-extended-user")
    app = App.objects.create(app_key="s13-cleanup-extended-app", name="S13 Extended")
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=now - timedelta(seconds=1),
    )
    original_expire_grant = GrantService.expire_grant

    def extend_before_expire(input_data: GrantExpirationInput) -> AccessGrant | None:
        _ = AccessGrant.objects.filter(
            user=input_data.user,
            app=input_data.app,
            is_current=True,
        ).update(
            grant_expires_at=now + timedelta(minutes=10),
        )
        return original_expire_grant(input_data)

    monkeypatch.setattr(GrantService, "expire_grant", staticmethod(extend_before_expire))

    # When: 清理任务处理这个已被延长到未来的候选 grant。
    result = cleanup_expired_grants(now=now)

    # Then: 清理任务跳过该候选, 不写过期审计也不改变授权版本。
    grant.refresh_from_db()
    assert result.expired_count == 0
    assert grant.status == GRANT_STATUS_ACTIVE
    assert grant.version == INITIAL_VERSION
    assert AuditLog.objects.filter(event_type="grant_expired").count() == 0
