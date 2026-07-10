from __future__ import annotations

from datetime import timedelta
from typing import Final

import pytest
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AppScope, AuthorizationGroup, Permission
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    GRANT_STATUS_EXPIRED,
    GRANT_STATUS_REVOKED,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from easyauth.grants.services import GrantExpirationInput, GrantService
from easyauth.tasks.grants import GRANT_EXPIRATION_REASON, cleanup_expired_grants

pytestmark = pytest.mark.django_db

INITIAL_VERSION: Final = 1
PARTIALLY_EXPIRED_VERSION: Final = 2
FULLY_EXPIRED_VERSION: Final = 3
EXPECTED_EXPIRATION_LOGS: Final = 2
DEFAULT_SCOPE_KEY: Final = "GLOBAL"


def _scoped_permission(app: App, *, key: str, name: str) -> Permission:
    _ = AppScope.objects.get_or_create(
        app=app,
        key=DEFAULT_SCOPE_KEY,
        defaults={"name": "Global"},
    )
    return Permission.objects.create(
        app=app,
        key=key,
        name=name,
        supported_scopes=[DEFAULT_SCOPE_KEY],
    )


def test_s13_cleanup_expired_memberships_keeps_parent_until_last_membership_expires() -> None:
    # Given: 当前授权包含一个已到期组链接和一个未来到期权限链接。
    now = timezone.now()
    final_cutoff = now + timedelta(minutes=10)
    user = UserMirror.objects.create(authentik_user_id="s13-cleanup-staged-user")
    app = App.objects.create(app_key="s13-cleanup-staged-app", name="S13 Cleanup Staged")
    group = AuthorizationGroup.objects.create(
        app=app,
        key="operator",
        kind="role",
        name="Operator",
    )
    permission = _scoped_permission(app, key="invoice.read", name="Read invoices")
    grant = AccessGrant.objects.create(user=user, app=app)
    due_group_link = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=now,
    )
    future_permission_link = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key=DEFAULT_SCOPE_KEY,
        expires_at=final_cutoff,
    )

    # When: 先清理部分到期链接并重复执行, 再清理最后一个到期链接并重复执行。
    partial = cleanup_expired_grants(now=now)
    repeated_partial = cleanup_expired_grants(now=now)

    grant.refresh_from_db()
    assert partial.expired_count == 1
    assert [item.id for item in partial.expired_grants] == [grant.id]
    assert repeated_partial.expired_count == 0
    assert not AccessGrantGroup.objects.filter(id=due_group_link.id).exists()
    assert AccessGrantPermission.objects.filter(id=future_permission_link.id).exists()
    assert grant.status == GRANT_STATUS_ACTIVE
    assert grant.is_current is True
    assert grant.version == PARTIALLY_EXPIRED_VERSION

    final = cleanup_expired_grants(now=final_cutoff)
    repeated_final = cleanup_expired_grants(now=final_cutoff)

    # Then: 只有到期链接被删除; 最后一个链接到期时父授权才退出当前 active 状态。
    grant.refresh_from_db()
    assert final.expired_count == 1
    assert [item.id for item in final.expired_grants] == [grant.id]
    assert repeated_final.expired_count == 0
    assert not AccessGrantPermission.objects.filter(id=future_permission_link.id).exists()
    assert grant.status == GRANT_STATUS_EXPIRED
    assert grant.is_current is False
    assert grant.version == FULLY_EXPIRED_VERSION
    audit_logs = AuditLog.objects.filter(event_type="grant_expired").order_by("created_at", "id")
    assert audit_logs.count() == EXPECTED_EXPIRATION_LOGS
    assert [audit_log.metadata["version"] for audit_log in audit_logs] == [
        PARTIALLY_EXPIRED_VERSION,
        FULLY_EXPIRED_VERSION,
    ]
    for audit_log in audit_logs:
        assert audit_log.actor_type == "system"
        assert audit_log.actor_id == "grant-expiration-cleanup"
        assert audit_log.metadata["reason"] == GRANT_EXPIRATION_REASON


def test_s13_cleanup_expired_memberships_skips_candidate_consumed_by_concurrent_revoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 清理任务选中含到期链接的 grant 后, 另一个撤权路径先消费了该 grant。
    now = timezone.now()
    user = UserMirror.objects.create(authentik_user_id="s13-cleanup-concurrent-user")
    app = App.objects.create(app_key="s13-cleanup-concurrent-app", name="S13 Concurrent")
    permission = _scoped_permission(app, key="invoice.read", name="Read invoices")
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key=DEFAULT_SCOPE_KEY,
        expires_at=now - timedelta(seconds=1),
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
    assert grant.is_current is False
    assert grant.version == PARTIALLY_EXPIRED_VERSION
    assert AuditLog.objects.filter(event_type="grant_expired").count() == 0


def test_s13_cleanup_expired_memberships_skips_candidate_extended_before_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 清理任务选中含到期链接的 grant 后, 链接在写入锁内复核前被延长。
    now = timezone.now()
    extended_until = now + timedelta(minutes=10)
    user = UserMirror.objects.create(authentik_user_id="s13-cleanup-extended-user")
    app = App.objects.create(app_key="s13-cleanup-extended-app", name="S13 Extended")
    permission = _scoped_permission(app, key="invoice.read", name="Read invoices")
    grant = AccessGrant.objects.create(user=user, app=app)
    link = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key=DEFAULT_SCOPE_KEY,
        expires_at=now - timedelta(seconds=1),
    )
    original_expire_grant = GrantService.expire_grant

    def extend_before_expire(input_data: GrantExpirationInput) -> AccessGrant | None:
        _ = AccessGrantPermission.objects.filter(id=link.id).update(expires_at=extended_until)
        return original_expire_grant(input_data)

    monkeypatch.setattr(GrantService, "expire_grant", staticmethod(extend_before_expire))

    # When: 清理任务处理这个已延长到未来的候选 grant, 并在同一截止时间重复执行。
    result = cleanup_expired_grants(now=now)
    repeated = cleanup_expired_grants(now=now)

    # Then: 两次清理都跳过该候选, 不删除链接、不写过期审计也不改变授权版本。
    grant.refresh_from_db()
    link.refresh_from_db()
    assert result.expired_count == 0
    assert repeated.expired_count == 0
    assert grant.status == GRANT_STATUS_ACTIVE
    assert grant.is_current is True
    assert grant.version == INITIAL_VERSION
    assert link.expires_at == extended_until
    assert AuditLog.objects.filter(event_type="grant_expired").count() == 0
