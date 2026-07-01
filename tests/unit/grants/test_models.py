from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AppScope, AuthorizationGroup, Permission, Role
from easyauth.grants.models import (
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
    AccessGrantRole,
)

pytestmark = pytest.mark.django_db


def test_timed_grant_requires_expiration_when_access_grant_is_cleaned() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-timed-no-expiration")
    app = App.objects.create(app_key="timed-no-expiration-app", name="Timed App")
    grant = AccessGrant(user=user, app=app, grant_type="timed")

    # When / Then
    with pytest.raises(ValidationError):
        grant.full_clean()


def test_permanent_grant_rejects_expiration_when_access_grant_is_cleaned() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-permanent-expiration")
    app = App.objects.create(app_key="permanent-expiration-app", name="Permanent App")
    grant = AccessGrant(
        user=user,
        app=app,
        grant_type="permanent",
        grant_expires_at=timezone.now(),
    )

    # When / Then
    with pytest.raises(ValidationError):
        grant.full_clean()


def test_user_app_allows_one_current_grant_when_duplicate_is_cleaned() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-current-grant")
    app = App.objects.create(app_key="current-grant-app", name="Current Grant App")
    _ = AccessGrant.objects.create(user=user, app=app, grant_type="permanent", is_current=True)
    duplicate = AccessGrant(user=user, app=app, grant_type="permanent", is_current=True)

    # When / Then
    with pytest.raises(ValidationError):
        duplicate.full_clean()


def test_user_app_allows_historical_grants_when_duplicate_is_not_current() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-historical-grant")
    app = App.objects.create(app_key="historical-grant-app", name="Historical Grant App")
    _ = AccessGrant.objects.create(user=user, app=app, grant_type="permanent", is_current=True)
    historical = AccessGrant(user=user, app=app, grant_type="permanent", is_current=False)

    # When
    historical.full_clean()

    # Then
    assert historical.is_current is False


def test_access_grant_role_rejects_cross_app_role_when_cleaned() -> None:
    # Given
    crm = App.objects.create(app_key="crm-grant-role", name="CRM")
    erp = App.objects.create(app_key="erp-grant-role", name="ERP")
    user = UserMirror.objects.create(authentik_user_id="user-grant-role")
    grant = AccessGrant.objects.create(user=user, app=crm, grant_type="permanent")
    role = Role.objects.create(app=erp, key="admin", name="Admin")
    grant_role = AccessGrantRole(grant=grant, role=role)

    # When / Then
    with pytest.raises(ValidationError):
        grant_role.full_clean()


def test_access_grant_permission_rejects_cross_app_permission_when_cleaned() -> None:
    # Given
    crm = App.objects.create(app_key="crm-grant-permission", name="CRM")
    erp = App.objects.create(app_key="erp-grant-permission", name="ERP")
    user = UserMirror.objects.create(authentik_user_id="user-grant-permission")
    grant = AccessGrant.objects.create(user=user, app=crm, grant_type="permanent")
    permission = Permission.objects.create(app=erp, key="invoice.read", name="Read invoices")
    grant_permission = AccessGrantPermission(grant=grant, permission=permission)

    # When / Then
    with pytest.raises(ValidationError):
        grant_permission.full_clean()


def test_access_grant_group_rejects_cross_app_group_when_cleaned() -> None:
    # Given
    crm = App.objects.create(app_key="crm-grant-group", name="CRM")
    erp = App.objects.create(app_key="erp-grant-group", name="ERP")
    user = UserMirror.objects.create(authentik_user_id="user-grant-group")
    grant = AccessGrant.objects.create(user=user, app=crm, grant_type="permanent")
    group = AuthorizationGroup.objects.create(app=erp, key="admin", kind="role", name="Admin")
    grant_group = AccessGrantGroup(grant=grant, authorization_group=group)

    # When / Then
    with pytest.raises(ValidationError):
        grant_group.full_clean()


def test_access_grant_permission_unique_constraint_includes_scope_key() -> None:
    # Given
    app = App.objects.create(app_key="scoped-permission-unique", name="Scoped App")
    user = UserMirror.objects.create(authentik_user_id="user-scoped-permission-unique")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type="permanent")
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="Global")
    _ = AppScope.objects.create(app=app, key="DEPARTMENT", name="Department")
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Read invoices",
        supported_scopes=["GLOBAL", "DEPARTMENT"],
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key="GLOBAL",
    )
    different_scope = AccessGrantPermission(
        grant=grant,
        permission=permission,
        scope_key="DEPARTMENT",
    )
    duplicate_scope = AccessGrantPermission(
        grant=grant,
        permission=permission,
        scope_key="GLOBAL",
    )

    # When
    different_scope.full_clean()
    different_scope.save()

    # Then
    with pytest.raises(ValidationError):
        duplicate_scope.full_clean()
    with pytest.raises(IntegrityError):
        AccessGrantPermission.objects.create(
            grant=grant,
            permission=permission,
            scope_key="GLOBAL",
        )


def test_access_grant_permission_rejects_unsupported_scope_when_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="unsupported-scope-app", name="Scoped App")
    user = UserMirror.objects.create(authentik_user_id="user-unsupported-scope")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type="permanent")
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="Global")
    _ = AppScope.objects.create(app=app, key="DEPARTMENT", name="Department")
    permission = Permission.objects.create(
        app=app,
        key="invoice.approve",
        name="Approve invoices",
        supported_scopes=["GLOBAL"],
    )
    grant_permission = AccessGrantPermission(
        grant=grant,
        permission=permission,
        scope_key="DEPARTMENT",
    )

    # When / Then
    with pytest.raises(ValidationError):
        grant_permission.full_clean()


def test_access_grant_permission_rejects_missing_scope_when_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="missing-scope-app", name="Scoped App")
    user = UserMirror.objects.create(authentik_user_id="user-missing-scope")
    grant = AccessGrant.objects.create(user=user, app=app, grant_type="permanent")
    permission = Permission.objects.create(
        app=app,
        key="invoice.export",
        name="Export invoices",
        supported_scopes=["TEAM"],
    )
    grant_permission = AccessGrantPermission(
        grant=grant,
        permission=permission,
        scope_key="TEAM",
    )

    # When / Then
    with pytest.raises(ValidationError):
        grant_permission.full_clean()
