from __future__ import annotations

from typing import Final

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, Permission, Role, RolePermission
from easyauth.grants.models import (
    GRANT_STATUS_EXPIRED,
    GRANT_STATUS_REVOKED,
    GRANT_TYPE_PERMANENT,
    AccessGrant,
    AccessGrantPermission,
    AccessGrantRole,
)
from easyauth.grants.query import resolve_user_permissions

pytestmark = pytest.mark.django_db

REVOKED_VERSION: Final = 2
EXPIRED_VERSION: Final = 3


def test_resolve_user_permissions_expands_role_and_direct_permissions_sorted_by_key() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-resolve-sorted")
    app = App.objects.create(app_key="resolve-sorted-app", name="Resolve Sorted App")
    admin = Role.objects.create(app=app, key="admin", name="Admin")
    auditor = Role.objects.create(app=app, key="auditor", name="Auditor")
    approve = Permission.objects.create(app=app, key="invoice.approve", name="Approve invoices")
    read = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    write = Permission.objects.create(app=app, key="invoice.write", name="Write invoices")
    _ = RolePermission.objects.create(role=admin, permission=write)
    _ = RolePermission.objects.create(role=auditor, permission=read)
    _ = RolePermission.objects.create(role=auditor, permission=write)
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantRole.objects.create(grant=grant, role=auditor)
    _ = AccessGrantRole.objects.create(grant=grant, role=admin)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=approve)

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.user_id == "user-resolve-sorted"
    assert snapshot.app_key == "resolve-sorted-app"
    assert snapshot.version == 1
    assert snapshot.roles == ("admin", "auditor")
    assert snapshot.permissions == ("invoice.approve", "invoice.read", "invoice.write")


def test_resolve_user_permissions_returns_empty_for_disabled_user() -> None:
    # Given
    user = UserMirror.objects.create(
        authentik_user_id="user-disabled-resolve",
        status="disabled",
    )
    app = App.objects.create(app_key="disabled-resolve-app", name="Disabled Resolve App")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    _ = AccessGrantPermission.objects.create(grant=grant, permission=permission)

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.version == 1
    assert snapshot.roles == ()
    assert snapshot.permissions == ()


def test_resolve_user_permissions_returns_empty_for_departed_user() -> None:
    # Given
    user = UserMirror.objects.create(
        authentik_user_id="user-departed-resolve",
        status="departed",
    )
    app = App.objects.create(app_key="departed-resolve-app", name="Departed Resolve App")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    _ = AccessGrantPermission.objects.create(grant=grant, permission=permission)

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.version == 1
    assert snapshot.roles == ()
    assert snapshot.permissions == ()


def test_resolve_user_permissions_returns_empty_for_revoked_or_expired_grant() -> None:
    # Given
    revoked_user = UserMirror.objects.create(authentik_user_id="user-revoked-resolve")
    expired_user = UserMirror.objects.create(authentik_user_id="user-expired-resolve")
    app = App.objects.create(app_key="inactive-grant-resolve-app", name="Inactive Grant App")
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    revoked = AccessGrant.objects.create(
        user=revoked_user,
        app=app,
        grant_type=GRANT_TYPE_PERMANENT,
        status=GRANT_STATUS_REVOKED,
        is_current=False,
        version=REVOKED_VERSION,
    )
    expired = AccessGrant.objects.create(
        user=expired_user,
        app=app,
        grant_type=GRANT_TYPE_PERMANENT,
        status=GRANT_STATUS_EXPIRED,
        is_current=False,
        version=EXPIRED_VERSION,
    )
    _ = AccessGrantPermission.objects.create(grant=revoked, permission=permission)
    _ = AccessGrantPermission.objects.create(grant=expired, permission=permission)

    # When
    revoked_snapshot = resolve_user_permissions(user=revoked_user, app=app)
    expired_snapshot = resolve_user_permissions(user=expired_user, app=app)

    # Then
    assert revoked_snapshot.version == REVOKED_VERSION
    assert revoked_snapshot.roles == ()
    assert revoked_snapshot.permissions == ()
    assert expired_snapshot.version == EXPIRED_VERSION
    assert expired_snapshot.roles == ()
    assert expired_snapshot.permissions == ()


def test_resolve_user_permissions_returns_empty_for_unknown_user_with_version_zero() -> None:
    # Given
    app = App.objects.create(app_key="unknown-user-resolve-app", name="Unknown User App")

    # When
    snapshot = resolve_user_permissions(user="unknown-user-resolve", app=app)

    # Then
    assert snapshot.user_id == "unknown-user-resolve"
    assert snapshot.app_key == "unknown-user-resolve-app"
    assert snapshot.version == 0
    assert snapshot.roles == ()
    assert snapshot.permissions == ()
