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
from easyauth.grants.services import (
    AuthorizationGroupGrantInput,
    GrantExpirationInput,
    GrantMutationExpiredError,
    GrantMutationInput,
    GrantService,
    ScopedDirectGrantInput,
)

pytestmark = pytest.mark.django_db

INITIAL_VERSION: Final = 1
CHANGED_VERSION: Final = 2
DEFAULT_SCOPE_KEY: Final = "GLOBAL"


def grant_target_id(user: UserMirror, app: App) -> str:
    return f"{user.authentik_user_id}:{app.app_key}"


def _scoped_permission(app: App, *, key: str, name: str) -> Permission:
    _ = AppScope.objects.get_or_create(app=app, key=DEFAULT_SCOPE_KEY, defaults={"name": "Global"})
    return Permission.objects.create(
        app=app,
        key=key,
        name=name,
        supported_scopes=[DEFAULT_SCOPE_KEY],
    )


def test_create_grant_creates_current_grant_with_groups_scoped_grants_and_audit_log() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-create-grant")
    app = App.objects.create(app_key="create-grant-app", name="Create Grant App")
    group = AuthorizationGroup.objects.create(
        app=app,
        key="operator",
        kind="role",
        name="Operator",
    )
    permission = _scoped_permission(app, key="invoice.read", name="Read invoices")

    # When
    grant = GrantService.create_grant(
        GrantMutationInput(
            user=user,
            app=app,
            authorization_groups=(AuthorizationGroupGrantInput(group, None),),
            direct_grants=(ScopedDirectGrantInput(permission, DEFAULT_SCOPE_KEY, None),),
            actor_type="admin",
            actor_id="admin-create",
        ),
    )

    # Then
    assert grant.status == GRANT_STATUS_ACTIVE
    assert grant.is_current is True
    assert grant.version == INITIAL_VERSION
    group_keys = list(
        AccessGrantGroup.objects.filter(grant=grant).values_list(
            "authorization_group__key",
            flat=True,
        ),
    )
    scoped_permission_keys = list(
        AccessGrantPermission.objects.filter(grant=grant).values_list(
            "permission__key",
            "scope_key",
        ),
    )
    assert group_keys == ["operator"]
    assert scoped_permission_keys == [("invoice.read", DEFAULT_SCOPE_KEY)]
    audit_log = AuditLog.objects.get(
        event_type="grant_created",
        target_id=grant_target_id(user, app),
    )
    assert audit_log.actor_type == "admin"
    assert audit_log.actor_id == "admin-create"
    assert audit_log.metadata["version"] == INITIAL_VERSION


def test_change_grant_replaces_current_group_and_scoped_direct_grants() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-change-grant")
    app = App.objects.create(app_key="change-grant-app", name="Change Grant App")
    old_group = AuthorizationGroup.objects.create(
        app=app,
        key="reader",
        kind="role",
        name="Reader",
    )
    new_group = AuthorizationGroup.objects.create(
        app=app,
        key="writer",
        kind="role",
        name="Writer",
    )
    old_permission = _scoped_permission(app, key="invoice.read", name="Read invoices")
    new_permission = _scoped_permission(app, key="invoice.write", name="Write invoices")
    current = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(grant=current, authorization_group=old_group)
    _ = AccessGrantPermission.objects.create(
        grant=current,
        permission=old_permission,
        scope_key=DEFAULT_SCOPE_KEY,
    )

    # When
    changed = GrantService.change_grant(
        GrantMutationInput(
            user=user,
            app=app,
            authorization_groups=(AuthorizationGroupGrantInput(new_group, None),),
            direct_grants=(ScopedDirectGrantInput(new_permission, DEFAULT_SCOPE_KEY, None),),
            actor_type="admin",
            actor_id="admin-change",
        ),
    )

    # Then
    assert AccessGrant.objects.filter(user=user, app=app).count() == 1
    assert changed.status == GRANT_STATUS_ACTIVE
    assert changed.is_current is True
    assert changed.version == CHANGED_VERSION
    group_keys = list(
        AccessGrantGroup.objects.filter(grant=changed).values_list(
            "authorization_group__key",
            flat=True,
        ),
    )
    scoped_permission_keys = list(
        AccessGrantPermission.objects.filter(grant=changed).values_list(
            "permission__key",
            "scope_key",
        ),
    )
    assert group_keys == ["writer"]
    assert scoped_permission_keys == [("invoice.write", DEFAULT_SCOPE_KEY)]
    audit_log = AuditLog.objects.get(
        event_type="grant_changed",
        target_id=grant_target_id(user, app),
    )
    assert audit_log.metadata["version"] == CHANGED_VERSION


def test_revoke_grant_marks_current_grant_revoked_and_is_idempotent() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-revoke-grant")
    app = App.objects.create(app_key="revoke-grant-app", name="Revoke Grant App")
    grant = AccessGrant.objects.create(user=user, app=app)

    # When
    revoked = GrantService.revoke_grant(
        user=user,
        app=app,
        actor_type="admin",
        actor_id="admin-revoke",
    )
    repeated = GrantService.revoke_grant(
        user=user,
        app=app,
        actor_type="admin",
        actor_id="admin-revoke",
    )

    # Then
    assert revoked is not None
    assert repeated is None
    grant.refresh_from_db()
    assert grant.status == GRANT_STATUS_REVOKED
    assert grant.is_current is False
    assert grant.version == CHANGED_VERSION
    assert (
        AuditLog.objects.filter(
            event_type="grant_revoked",
            target_id=grant_target_id(user, app),
        ).count()
        == 1
    )


def test_expire_grant_marks_current_timed_grant_expired_and_is_idempotent() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-expire-grant")
    app = App.objects.create(app_key="expire-grant-app", name="Expire Grant App")
    grant = AccessGrant.objects.create(user=user, app=app)
    permission = _scoped_permission(app, key="invoice.expiring", name="Expiring invoice")
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key=DEFAULT_SCOPE_KEY,
        expires_at=timezone.now(),
    )

    # When
    expired = GrantService.expire_grant(
        GrantExpirationInput(
            user=user,
            app=app,
            actor_type="system",
            actor_id="grant-expirer",
        ),
    )
    repeated = GrantService.expire_grant(
        GrantExpirationInput(
            user=user,
            app=app,
            actor_type="system",
            actor_id="grant-expirer",
        ),
    )

    # Then
    assert expired is not None
    assert repeated is None
    grant.refresh_from_db()
    assert grant.status == GRANT_STATUS_EXPIRED
    assert grant.is_current is False
    assert grant.version == CHANGED_VERSION
    assert (
        AuditLog.objects.filter(
            event_type="grant_expired",
            target_id=grant_target_id(user, app),
        ).count()
        == 1
    )


def test_change_grant_without_current_grant_creates_initial_current_grant() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-change-without-current")
    app = App.objects.create(app_key="change-without-current-app", name="Change Without Current")
    group = AuthorizationGroup.objects.create(
        app=app,
        key="auditor",
        kind="role",
        name="Auditor",
    )

    # When
    grant = GrantService.change_grant(
        GrantMutationInput(
            user=user,
            app=app,
            authorization_groups=(AuthorizationGroupGrantInput(group, None),),
            direct_grants=(),
            actor_type="admin",
            actor_id="admin-initial-change",
        ),
    )

    # Then
    assert grant.version == INITIAL_VERSION
    assert grant.is_current is True
    group_keys = list(
        AccessGrantGroup.objects.filter(grant=grant).values_list(
            "authorization_group__key",
            flat=True,
        ),
    )
    assert group_keys == ["auditor"]


def test_change_grant_preserves_distinct_direct_grants_for_same_permission_across_scopes() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-change-scopes")
    app = App.objects.create(app_key="change-scopes-app", name="Change Scopes")
    _ = AppScope.objects.create(app=app, key="SELF", name="Self")
    _ = AppScope.objects.create(app=app, key="TEAM", name="Team")
    permission = Permission.objects.create(
        app=app,
        key="invoice.export",
        name="Export invoices",
        supported_scopes=["SELF", "TEAM"],
    )

    # When
    grant = GrantService.change_grant(
        GrantMutationInput(
            user=user,
            app=app,
            authorization_groups=(),
            direct_grants=(
                ScopedDirectGrantInput(permission, "SELF", None),
                ScopedDirectGrantInput(permission, "TEAM", None),
            ),
            actor_type="admin",
            actor_id="admin-scopes",
        ),
    )

    # Then
    scoped_permission_keys = list(
        AccessGrantPermission.objects.filter(grant=grant).values_list(
            "permission__key",
            "scope_key",
        ),
    )
    assert scoped_permission_keys == [
        ("invoice.export", "SELF"),
        ("invoice.export", "TEAM"),
    ]


@pytest.mark.parametrize(
    ("expiration_offset", "suffix"),
    [(timedelta(seconds=-1), "past"), (timedelta(0), "now")],
)
def test_create_grant_rejects_expired_membership_atomically(
    monkeypatch: pytest.MonkeyPatch,
    expiration_offset: timedelta,
    suffix: str,
) -> None:
    # Given: 新授权包含已过期或恰好在当前时刻到期的成员事实。
    now = timezone.now()
    user = UserMirror.objects.create(authentik_user_id=f"create-expired-{suffix}")
    app = App.objects.create(app_key=f"create-expired-{suffix}", name="Expired")
    group = AuthorizationGroup.objects.create(app=app, key="reader", kind="role", name="Reader")
    monkeypatch.setattr("easyauth.grants.services.timezone.now", lambda: now)

    # When / Then: 唯一写边界快速失败, 且不留下父事实或审计事实。
    with pytest.raises(GrantMutationExpiredError):
        _ = GrantService.create_grant(
            GrantMutationInput(
                user=user,
                app=app,
                authorization_groups=(
                    AuthorizationGroupGrantInput(group, now + expiration_offset),
                ),
            ),
        )

    assert AccessGrant.objects.filter(user=user, app=app).count() == 0
    assert AuditLog.objects.filter(target_id=grant_target_id(user, app)).count() == 0


@pytest.mark.parametrize(
    ("expiration_offset", "suffix"),
    [(timedelta(seconds=-1), "past"), (timedelta(0), "now")],
)
def test_change_grant_rejects_expired_membership_atomically(
    monkeypatch: pytest.MonkeyPatch,
    expiration_offset: timedelta,
    suffix: str,
) -> None:
    # Given: 当前授权有永久成员, 变更目标包含已过期或当前时刻到期的成员。
    now = timezone.now()
    user = UserMirror.objects.create(authentik_user_id=f"change-expired-{suffix}")
    app = App.objects.create(app_key=f"change-expired-{suffix}", name="Expired")
    old_group = AuthorizationGroup.objects.create(
        app=app,
        key="reader",
        kind="role",
        name="Reader",
    )
    new_group = AuthorizationGroup.objects.create(
        app=app,
        key="writer",
        kind="role",
        name="Writer",
    )
    current = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=current,
        authorization_group=old_group,
        expires_at=None,
    )
    monkeypatch.setattr("easyauth.grants.services.timezone.now", lambda: now)

    # When / Then: 变更整体失败, 旧版本和成员事实保持不变。
    with pytest.raises(GrantMutationExpiredError):
        _ = GrantService.change_grant(
            GrantMutationInput(
                user=user,
                app=app,
                authorization_groups=(
                    AuthorizationGroupGrantInput(new_group, now + expiration_offset),
                ),
            ),
        )

    current.refresh_from_db()
    assert current.version == INITIAL_VERSION
    assert current.status == GRANT_STATUS_ACTIVE
    assert current.is_current is True
    assert list(
        AccessGrantGroup.objects.filter(grant=current).values_list(
            "authorization_group__key",
            "expires_at",
        ),
    ) == [("reader", None)]
    assert AuditLog.objects.filter(target_id=grant_target_id(user, app)).count() == 0
