from __future__ import annotations

from importlib import import_module

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AppScope, AuthorizationGroup, Permission
from easyauth.grants.models import (
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)

pytestmark = pytest.mark.django_db


def test_user_app_allows_one_current_grant_when_duplicate_is_cleaned() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-current-grant")
    app = App.objects.create(app_key="current-grant-app", name="Current Grant App")
    _ = AccessGrant.objects.create(user=user, app=app, is_current=True)
    duplicate = AccessGrant(user=user, app=app, is_current=True)

    # When / Then
    with pytest.raises(ValidationError):
        duplicate.full_clean()


def test_user_app_allows_historical_grants_when_duplicate_is_not_current() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-historical-grant")
    app = App.objects.create(app_key="historical-grant-app", name="Historical Grant App")
    _ = AccessGrant.objects.create(user=user, app=app, is_current=True)
    historical = AccessGrant(
        user=user,
        app=app,
        is_current=False,
        version=2,
    )

    # When
    historical.full_clean()

    # Then
    assert historical.is_current is False


def test_access_grant_permission_rejects_cross_app_permission_when_cleaned() -> None:
    # Given
    crm = App.objects.create(app_key="crm-grant-permission", name="CRM")
    erp = App.objects.create(app_key="erp-grant-permission", name="ERP")
    user = UserMirror.objects.create(authentik_user_id="user-grant-permission")
    grant = AccessGrant.objects.create(user=user, app=crm)
    permission = Permission.objects.create(app=erp, key="invoice.read", name="Read invoices")
    grant_permission = AccessGrantPermission(grant=grant, permission=permission)

    # When / Then
    with pytest.raises(ValidationError):
        grant_permission.full_clean()


def test_access_grant_permission_cross_app_is_rejected_by_database() -> None:
    # Given
    crm = App.objects.create(app_key="crm-grant-permission-db", name="CRM")
    erp = App.objects.create(app_key="erp-grant-permission-db", name="ERP")
    user = UserMirror.objects.create(authentik_user_id="user-grant-permission-db")
    grant = AccessGrant.objects.create(user=user, app=crm)
    _ = AppScope.objects.create(app=crm, key="GLOBAL", name="Global")
    permission = Permission.objects.create(
        app=erp,
        key="invoice.read.db",
        name="Read invoices",
        supported_scopes=["GLOBAL"],
    )

    # When / Then
    with pytest.raises(IntegrityError):
        _ = AccessGrantPermission.objects.create(
            grant=grant,
            permission=permission,
            scope_key="GLOBAL",
        )


def test_access_grant_group_rejects_cross_app_group_when_cleaned() -> None:
    # Given
    crm = App.objects.create(app_key="crm-grant-group", name="CRM")
    erp = App.objects.create(app_key="erp-grant-group", name="ERP")
    user = UserMirror.objects.create(authentik_user_id="user-grant-group")
    grant = AccessGrant.objects.create(user=user, app=crm)
    group = AuthorizationGroup.objects.create(app=erp, key="admin", kind="role", name="Admin")
    grant_group = AccessGrantGroup(grant=grant, authorization_group=group)

    # When / Then
    with pytest.raises(ValidationError):
        grant_group.full_clean()


def test_access_grant_group_cross_app_is_rejected_by_database() -> None:
    # Given
    crm = App.objects.create(app_key="crm-grant-group-db", name="CRM")
    erp = App.objects.create(app_key="erp-grant-group-db", name="ERP")
    user = UserMirror.objects.create(authentik_user_id="user-grant-group-db")
    grant = AccessGrant.objects.create(user=user, app=crm)
    group = AuthorizationGroup.objects.create(app=erp, key="admin-db", kind="role", name="Admin")

    # When / Then
    with pytest.raises(IntegrityError):
        _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=group)


@pytest.mark.django_db(transaction=True)
def test_access_grant_group_migration_scan_blocks_existing_bad_rows() -> None:
    # Given
    migration = import_module("easyauth.grants.migrations.0007_access_grant_relationship_triggers")
    crm = App.objects.create(app_key="crm-grant-group-scan", name="CRM")
    erp = App.objects.create(app_key="erp-grant-group-scan", name="ERP")
    user = UserMirror.objects.create(authentik_user_id="user-grant-group-scan")
    grant = AccessGrant.objects.create(user=user, app=crm)
    group = AuthorizationGroup.objects.create(app=erp, key="admin-scan", kind="role", name="Admin")

    with connection.schema_editor() as schema_editor:
        migration.drop_triggers(None, schema_editor)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO grants_accessgrantgroup
                    (grant_id, authorization_group_id, expires_at, created_at)
                VALUES (%s, %s, NULL, CURRENT_TIMESTAMP)
                """,
                [grant.id, group.id],
            )

        # When / Then
        with (
            connection.schema_editor() as schema_editor,
            pytest.raises(migration.AccessGrantRelationshipMigrationError, match="count=1"),
        ):
            migration.assert_existing_relationships(None, schema_editor)
    finally:
        AccessGrantGroup.objects.filter(grant=grant, authorization_group=group).delete()
        with connection.schema_editor() as schema_editor:
            migration.install_triggers(None, schema_editor)


def test_access_grant_group_raw_cross_app_write_is_rejected_by_database() -> None:
    # Given
    crm = App.objects.create(app_key="crm-grant-group-raw", name="CRM")
    erp = App.objects.create(app_key="erp-grant-group-raw", name="ERP")
    user = UserMirror.objects.create(authentik_user_id="user-grant-group-raw")
    grant = AccessGrant.objects.create(user=user, app=crm)
    group = AuthorizationGroup.objects.create(app=erp, key="admin-raw", kind="role", name="Admin")

    # When / Then
    with pytest.raises(DatabaseError), connection.cursor() as cursor:
        cursor.execute(
            """
                INSERT INTO grants_accessgrantgroup
                    (grant_id, authorization_group_id, expires_at, created_at)
                VALUES (%s, %s, NULL, CURRENT_TIMESTAMP)
                """,
            [grant.id, group.id],
        )


def test_access_grant_permission_unique_constraint_includes_scope_key() -> None:
    # Given
    app = App.objects.create(app_key="scoped-permission-unique", name="Scoped App")
    user = UserMirror.objects.create(authentik_user_id="user-scoped-permission-unique")
    grant = AccessGrant.objects.create(user=user, app=app)
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
    grant = AccessGrant.objects.create(user=user, app=app)
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
    grant = AccessGrant.objects.create(user=user, app=app)
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
