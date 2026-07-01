from __future__ import annotations

from typing import Final

import pytest
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.grants.models import (
    GRANT_STATUS_EXPIRED,
    GRANT_STATUS_REVOKED,
    GRANT_TYPE_PERMANENT,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from easyauth.grants.query import ExpandedGrant, GroupSnapshot, resolve_user_permissions

pytestmark = pytest.mark.django_db

REVOKED_VERSION: Final = 2
EXPIRED_VERSION: Final = 3
UNKNOWN_USER_CATALOG_VERSION: Final = 12


def test_resolve_user_permissions_expands_group_grants_and_sorts_groups_and_grants() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-resolve-groups")
    app = App.objects.create(app_key="resolve-groups-app", name="Resolve Groups App")
    _scope(app, "SELF")
    _scope(app, "TEAM")
    sales = AuthorizationGroup.objects.create(app=app, key="sales", kind="role", name="销售")
    finance = AuthorizationGroup.objects.create(app=app, key="finance", kind="bundle", name="财务")
    approve = _permission(app, "invoice.approve", scopes=["TEAM"])
    read = _permission(app, "invoice.read", scopes=["SELF"])
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=sales,
        permission=read,
        scope_key="SELF",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=finance,
        permission=approve,
        scope_key="TEAM",
    )
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=sales)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=finance)

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.user_id == "user-resolve-groups"
    assert snapshot.app_key == "resolve-groups-app"
    assert snapshot.grant_version == 1
    assert snapshot.catalog_version == 1
    assert snapshot.snapshot_version == "1.1"
    assert snapshot.groups == (
        GroupSnapshot(key="finance", kind="bundle", name="财务"),
        GroupSnapshot(key="sales", kind="role", name="销售"),
    )
    assert snapshot.grants == (
        ExpandedGrant(
            permission="invoice.approve",
            scope="TEAM",
            source_type="group",
            source_key="finance",
        ),
        ExpandedGrant(
            permission="invoice.read",
            scope="SELF",
            source_type="group",
            source_key="sales",
        ),
    )


def test_resolve_user_permissions_expands_direct_scoped_grants() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-direct-scoped")
    app = App.objects.create(app_key="direct-scoped-app", name="Direct Scoped App")
    _scope(app, "SELF")
    permission = _permission(app, "customer.profile.export", scopes=["SELF"])
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key="SELF",
    )

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.groups == ()
    assert snapshot.grants == (
        ExpandedGrant(
            permission="customer.profile.export",
            scope="SELF",
            source_type="direct",
            source_key="",
        ),
    )


def test_resolve_user_permissions_preserves_same_permission_with_different_scopes() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-multi-scope")
    app = App.objects.create(app_key="multi-scope-app", name="Multi Scope App")
    _scope(app, "SELF")
    _scope(app, "TEAM")
    permission = _permission(app, "invoice.read", scopes=["SELF", "TEAM"])
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=permission, scope_key="TEAM")
    _ = AccessGrantPermission.objects.create(grant=grant, permission=permission, scope_key="SELF")

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.grants == (
        ExpandedGrant("invoice.read", "SELF", "direct", ""),
        ExpandedGrant("invoice.read", "TEAM", "direct", ""),
    )


def test_resolve_user_permissions_keeps_group_and_direct_sources_for_same_scope() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-mixed-source")
    app = App.objects.create(app_key="mixed-source-app", name="Mixed Source App")
    _scope(app, "SELF")
    group = AuthorizationGroup.objects.create(app=app, key="sales", kind="role", name="Sales")
    permission = _permission(app, "invoice.read", scopes=["SELF"])
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key="SELF",
    )
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=group)
    _ = AccessGrantPermission.objects.create(grant=grant, permission=permission, scope_key="SELF")

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.grants == (
        ExpandedGrant("invoice.read", "SELF", "direct", ""),
        ExpandedGrant("invoice.read", "SELF", "group", "sales"),
    )


def test_resolve_user_permissions_filters_inactive_and_deprecated_catalog_entries() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-filtered-catalog")
    app = App.objects.create(app_key="filtered-catalog-app", name="Filtered Catalog App")
    _scope(app, "SELF")
    _scope(app, "INACTIVE", is_active=False)
    active_group = AuthorizationGroup.objects.create(
        app=app,
        key="active",
        kind="role",
        name="Active",
    )
    inactive_group = AuthorizationGroup.objects.create(
        app=app,
        key="inactive",
        kind="role",
        name="Inactive",
        is_active=False,
    )
    active_permission = _permission(app, "invoice.active", scopes=["SELF"])
    inactive_permission = _permission(app, "invoice.inactive", scopes=["SELF"], is_active=False)
    deprecated_permission = _permission(
        app,
        "invoice.deprecated",
        scopes=["SELF"],
        deprecated_at=timezone.now(),
    )
    inactive_scope_permission = _permission(app, "invoice.inactive-scope", scopes=["INACTIVE"])
    inactive_group_permission = _permission(app, "invoice.inactive-group", scopes=["SELF"])
    inactive_group_grant_permission = _permission(
        app,
        "invoice.inactive-group-grant",
        scopes=["SELF"],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=active_group,
        permission=active_permission,
        scope_key="SELF",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=active_group,
        permission=inactive_permission,
        scope_key="SELF",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=active_group,
        permission=deprecated_permission,
        scope_key="SELF",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=active_group,
        permission=inactive_scope_permission,
        scope_key="INACTIVE",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=active_group,
        permission=inactive_group_grant_permission,
        scope_key="SELF",
        is_active=False,
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=inactive_group,
        permission=inactive_group_permission,
        scope_key="SELF",
    )
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=active_group)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=inactive_group)
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=active_permission,
        scope_key="SELF",
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=inactive_permission,
        scope_key="SELF",
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=deprecated_permission,
        scope_key="SELF",
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=inactive_scope_permission,
        scope_key="INACTIVE",
    )

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.groups == (GroupSnapshot(key="active", kind="role", name="Active"),)
    assert snapshot.grants == (
        ExpandedGrant("invoice.active", "SELF", "direct", ""),
        ExpandedGrant("invoice.active", "SELF", "group", "active"),
    )


def test_resolve_user_permissions_returns_catalog_and_snapshot_versions_for_empty_results() -> None:
    # Given
    app = App.objects.create(
        app_key="unknown-user-resolve-app",
        name="Unknown User App",
        catalog_version=UNKNOWN_USER_CATALOG_VERSION,
    )

    # When
    snapshot = resolve_user_permissions(user="unknown-user-resolve", app=app)

    # Then
    assert snapshot.user_id == "unknown-user-resolve"
    assert snapshot.app_key == "unknown-user-resolve-app"
    assert snapshot.grant_version == 0
    assert snapshot.catalog_version == UNKNOWN_USER_CATALOG_VERSION
    assert snapshot.snapshot_version == "0.12"
    assert snapshot.groups == ()
    assert snapshot.grants == ()


def test_resolve_user_permissions_returns_empty_for_disabled_user() -> None:
    # Given
    user = UserMirror.objects.create(
        authentik_user_id="user-disabled-resolve",
        status="disabled",
    )
    app = App.objects.create(app_key="disabled-resolve-app", name="Disabled Resolve App")
    _scope(app, "SELF")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    permission = _permission(app, "invoice.read", scopes=["SELF"])
    _ = AccessGrantPermission.objects.create(grant=grant, permission=permission, scope_key="SELF")

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.grant_version == 1
    assert snapshot.groups == ()
    assert snapshot.grants == ()


def test_resolve_user_permissions_returns_empty_for_departed_user() -> None:
    # Given
    user = UserMirror.objects.create(
        authentik_user_id="user-departed-resolve",
        status="departed",
    )
    app = App.objects.create(app_key="departed-resolve-app", name="Departed Resolve App")
    _scope(app, "SELF")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type=GRANT_TYPE_PERMANENT)
    permission = _permission(app, "invoice.read", scopes=["SELF"])
    _ = AccessGrantPermission.objects.create(grant=grant, permission=permission, scope_key="SELF")

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.grant_version == 1
    assert snapshot.groups == ()
    assert snapshot.grants == ()


def test_resolve_user_permissions_returns_empty_for_revoked_or_expired_grant() -> None:
    # Given
    revoked_user = UserMirror.objects.create(authentik_user_id="user-revoked-resolve")
    expired_user = UserMirror.objects.create(authentik_user_id="user-expired-resolve")
    app = App.objects.create(app_key="inactive-grant-resolve-app", name="Inactive Grant App")
    _scope(app, "SELF")
    permission = _permission(app, "invoice.read", scopes=["SELF"])
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
    _ = AccessGrantPermission.objects.create(grant=revoked, permission=permission, scope_key="SELF")
    _ = AccessGrantPermission.objects.create(grant=expired, permission=permission, scope_key="SELF")

    # When
    revoked_snapshot = resolve_user_permissions(user=revoked_user, app=app)
    expired_snapshot = resolve_user_permissions(user=expired_user, app=app)

    # Then
    assert revoked_snapshot.grant_version == REVOKED_VERSION
    assert revoked_snapshot.groups == ()
    assert revoked_snapshot.grants == ()
    assert expired_snapshot.grant_version == EXPIRED_VERSION
    assert expired_snapshot.groups == ()
    assert expired_snapshot.grants == ()


def _scope(app: App, key: str, *, is_active: bool = True) -> AppScope:
    return AppScope.objects.create(app=app, key=key, name=key.title(), is_active=is_active)


def _permission(
    app: App,
    key: str,
    *,
    scopes: list[str],
    is_active: bool = True,
    deprecated_at: object | None = None,
) -> Permission:
    return Permission.objects.create(
        app=app,
        key=key,
        name=key,
        supported_scopes=scopes,
        is_active=is_active,
        deprecated_at=deprecated_at,
    )
