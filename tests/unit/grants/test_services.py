from __future__ import annotations

from typing import Final

import pytest
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, Permission, Role, RolePermission
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    GRANT_STATUS_EXPIRED,
    GRANT_STATUS_REVOKED,
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    AccessGrant,
    AccessGrantPermission,
    AccessGrantRole,
)
from easyauth.grants.services import GrantExpirationInput, GrantMutationInput, GrantService

pytestmark = pytest.mark.django_db

INITIAL_VERSION: Final = 1
CHANGED_VERSION: Final = 2


def grant_target_id(user: UserMirror, app: App) -> str:
    return f"{user.authentik_user_id}:{app.app_key}"


def test_create_grant_creates_current_grant_with_memberships_and_audit_log() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-create-grant")
    app = App.objects.create(app_key="create-grant-app", name="Create Grant App")
    role = Role.objects.create(app=app, key="operator", name="Operator")
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")

    # When
    grant = GrantService.create_grant(
        GrantMutationInput(
            user=user,
            app=app,
            grant_type=GRANT_TYPE_PERMANENT,
            grant_expires_at=None,
            roles=(role,),
            permissions=(permission,),
            actor_type="admin",
            actor_id="admin-create",
        ),
    )

    # Then
    assert grant.status == GRANT_STATUS_ACTIVE
    assert grant.is_current is True
    assert grant.version == INITIAL_VERSION
    role_keys = list(
        AccessGrantRole.objects.filter(grant=grant).values_list("role__key", flat=True),
    )
    permission_keys = list(
        AccessGrantPermission.objects.filter(grant=grant).values_list("permission__key", flat=True),
    )
    assert role_keys == ["operator"]
    assert permission_keys == ["invoice.read"]
    audit_log = AuditLog.objects.get(
        event_type="grant_created",
        target_id=grant_target_id(user, app),
    )
    assert audit_log.actor_type == "admin"
    assert audit_log.actor_id == "admin-create"
    assert audit_log.metadata["version"] == INITIAL_VERSION


def test_change_grant_replaces_current_grant_memberships_and_records_audit_log() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-change-grant")
    app = App.objects.create(app_key="change-grant-app", name="Change Grant App")
    old_role = Role.objects.create(app=app, key="reader", name="Reader")
    new_role = Role.objects.create(app=app, key="writer", name="Writer")
    old_permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    new_permission = Permission.objects.create(app=app, key="invoice.write", name="Write invoices")
    current = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantRole.objects.create(grant=current, role=old_role)
    _ = AccessGrantPermission.objects.create(grant=current, permission=old_permission)

    # When
    changed = GrantService.change_grant(
        GrantMutationInput(
            user=user,
            app=app,
            grant_type=GRANT_TYPE_PERMANENT,
            grant_expires_at=None,
            roles=(new_role,),
            permissions=(new_permission,),
            actor_type="admin",
            actor_id="admin-change",
        ),
    )

    # Then
    assert AccessGrant.objects.filter(user=user, app=app).count() == 1
    assert changed.status == GRANT_STATUS_ACTIVE
    assert changed.is_current is True
    assert changed.version == CHANGED_VERSION
    role_keys = list(
        AccessGrantRole.objects.filter(grant=changed).values_list("role__key", flat=True),
    )
    permission_keys = list(
        AccessGrantPermission.objects.filter(grant=changed).values_list(
            "permission__key",
            flat=True,
        ),
    )
    assert role_keys == ["writer"]
    assert permission_keys == ["invoice.write"]
    audit_log = AuditLog.objects.get(
        event_type="grant_changed",
        target_id=grant_target_id(user, app),
    )
    assert audit_log.metadata["version"] == CHANGED_VERSION


def test_revoke_grant_marks_current_grant_revoked_and_is_idempotent() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-revoke-grant")
    app = App.objects.create(app_key="revoke-grant-app", name="Revoke Grant App")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)

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
    assert AuditLog.objects.filter(
        event_type="grant_revoked",
        target_id=grant_target_id(user, app),
    ).count() == 1


def test_expire_grant_marks_current_timed_grant_expired_and_is_idempotent() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-expire-grant")
    app = App.objects.create(app_key="expire-grant-app", name="Expire Grant App")
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=timezone.now(),
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
    assert AuditLog.objects.filter(
        event_type="grant_expired",
        target_id=grant_target_id(user, app),
    ).count() == 1


def test_change_grant_without_current_grant_creates_initial_current_grant() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-change-without-current")
    app = App.objects.create(app_key="change-without-current-app", name="Change Without Current")
    role = Role.objects.create(app=app, key="auditor", name="Auditor")
    permission = Permission.objects.create(app=app, key="audit.read", name="Read audit")
    _ = RolePermission.objects.create(role=role, permission=permission)

    # When
    grant = GrantService.change_grant(
        GrantMutationInput(
            user=user,
            app=app,
            grant_type=GRANT_TYPE_PERMANENT,
            grant_expires_at=None,
            roles=(role,),
            permissions=(),
            actor_type="admin",
            actor_id="admin-initial-change",
        ),
    )

    # Then
    assert grant.version == INITIAL_VERSION
    assert grant.is_current is True
    role_keys = list(
        AccessGrantRole.objects.filter(grant=grant).values_list("role__key", flat=True),
    )
    assert role_keys == ["auditor"]
