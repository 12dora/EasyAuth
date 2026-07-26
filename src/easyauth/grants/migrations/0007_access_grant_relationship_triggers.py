# ruff: noqa: ANN001, ANN201, ANN202, RUF012
# pyright: reportAny=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportMissingParameterType=false, reportUnannotatedClassAttribute=false
from django.db import migrations


class AccessGrantRelationshipMigrationError(RuntimeError):
    pass


def _relation_blocker(cursor, *, label, count_sql, sample_sql):
    cursor.execute(count_sql)
    count, min_id, max_id = cursor.fetchone()
    if count == 0:
        return
    cursor.execute(sample_sql)
    sample_ids = ", ".join(str(row[0]) for row in cursor.fetchall())
    message = (
        f"{label} 迁移被阻断: 存在跨 App 或孤儿关系, "
        f"count={count}, pk_range={min_id}..{max_id}, sample_ids={sample_ids}"
    )
    raise AccessGrantRelationshipMigrationError(message)


def assert_existing_relationships(apps, schema_editor):
    del apps
    cursor = schema_editor.connection.cursor()
    _relation_blocker(
        cursor,
        label="AccessGrantGroup.authorization_group",
        count_sql="""
            SELECT COUNT(*), MIN(grant_group.id), MAX(grant_group.id)
            FROM grants_accessgrantgroup grant_group
            JOIN grants_accessgrant access_grant
              ON access_grant.id = grant_group.grant_id
            JOIN applications_authorizationgroup auth_group
              ON auth_group.id = grant_group.authorization_group_id
            WHERE access_grant.app_id <> auth_group.app_id
        """,
        sample_sql="""
            SELECT grant_group.id
            FROM grants_accessgrantgroup grant_group
            JOIN grants_accessgrant access_grant
              ON access_grant.id = grant_group.grant_id
            JOIN applications_authorizationgroup auth_group
              ON auth_group.id = grant_group.authorization_group_id
            WHERE access_grant.app_id <> auth_group.app_id
            ORDER BY grant_group.id
            LIMIT 20
        """,
    )
    _relation_blocker(
        cursor,
        label="AccessGrantPermission.permission",
        count_sql="""
            SELECT COUNT(*), MIN(grant_permission.id), MAX(grant_permission.id)
            FROM grants_accessgrantpermission grant_permission
            JOIN grants_accessgrant access_grant
              ON access_grant.id = grant_permission.grant_id
            JOIN applications_permission permission
              ON permission.id = grant_permission.permission_id
            WHERE access_grant.app_id <> permission.app_id
        """,
        sample_sql="""
            SELECT grant_permission.id
            FROM grants_accessgrantpermission grant_permission
            JOIN grants_accessgrant access_grant
              ON access_grant.id = grant_permission.grant_id
            JOIN applications_permission permission
              ON permission.id = grant_permission.permission_id
            WHERE access_grant.app_id <> permission.app_id
            ORDER BY grant_permission.id
            LIMIT 20
        """,
    )
    _relation_blocker(
        cursor,
        label="AccessGrantPermission.scope",
        count_sql="""
            SELECT COUNT(*), MIN(grant_permission.id), MAX(grant_permission.id)
            FROM grants_accessgrantpermission grant_permission
            JOIN grants_accessgrant access_grant
              ON access_grant.id = grant_permission.grant_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM applications_appscope app_scope
                WHERE app_scope.app_id = access_grant.app_id
                  AND app_scope.key = grant_permission.scope_key
            )
        """,
        sample_sql="""
            SELECT grant_permission.id
            FROM grants_accessgrantpermission grant_permission
            JOIN grants_accessgrant access_grant
              ON access_grant.id = grant_permission.grant_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM applications_appscope app_scope
                WHERE app_scope.app_id = access_grant.app_id
                  AND app_scope.key = grant_permission.scope_key
            )
            ORDER BY grant_permission.id
            LIMIT 20
        """,
    )


def install_triggers(apps, schema_editor):
    del apps
    cursor = schema_editor.connection.cursor()
    if schema_editor.connection.vendor == "sqlite":
        cursor.executescript(
            """
            CREATE TRIGGER grants_access_grant_group_app_guard_insert
            BEFORE INSERT ON grants_accessgrantgroup
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'access grant group app mismatch')
                WHERE (
                    SELECT app_id FROM grants_accessgrant WHERE id = NEW.grant_id
                ) <> (
                    SELECT app_id FROM applications_authorizationgroup
                    WHERE id = NEW.authorization_group_id
                );
            END;
            CREATE TRIGGER grants_access_grant_group_app_guard_update
            BEFORE UPDATE OF grant_id, authorization_group_id ON grants_accessgrantgroup
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'access grant group app mismatch')
                WHERE (
                    SELECT app_id FROM grants_accessgrant WHERE id = NEW.grant_id
                ) <> (
                    SELECT app_id FROM applications_authorizationgroup
                    WHERE id = NEW.authorization_group_id
                );
            END;
            CREATE TRIGGER grants_access_grant_permission_app_guard_insert
            BEFORE INSERT ON grants_accessgrantpermission
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'access grant permission app mismatch')
                WHERE (
                    SELECT app_id FROM grants_accessgrant WHERE id = NEW.grant_id
                ) <> (
                    SELECT app_id FROM applications_permission WHERE id = NEW.permission_id
                );
                SELECT RAISE(ABORT, 'access grant permission scope app mismatch')
                WHERE NOT EXISTS (
                    SELECT 1 FROM applications_appscope app_scope
                    JOIN grants_accessgrant access_grant ON access_grant.id = NEW.grant_id
                    WHERE app_scope.app_id = access_grant.app_id
                      AND app_scope.key = NEW.scope_key
                );
            END;
            CREATE TRIGGER grants_access_grant_permission_app_guard_update
            BEFORE UPDATE OF grant_id, permission_id, scope_key ON grants_accessgrantpermission
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'access grant permission app mismatch')
                WHERE (
                    SELECT app_id FROM grants_accessgrant WHERE id = NEW.grant_id
                ) <> (
                    SELECT app_id FROM applications_permission WHERE id = NEW.permission_id
                );
                SELECT RAISE(ABORT, 'access grant permission scope app mismatch')
                WHERE NOT EXISTS (
                    SELECT 1 FROM applications_appscope app_scope
                    JOIN grants_accessgrant access_grant ON access_grant.id = NEW.grant_id
                    WHERE app_scope.app_id = access_grant.app_id
                      AND app_scope.key = NEW.scope_key
                );
            END;
            """
        )
        return
    if schema_editor.connection.vendor == "postgresql":
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION grants_access_grant_group_guard()
            RETURNS trigger AS $$
            BEGIN
                IF (
                    SELECT app_id FROM grants_accessgrant WHERE id = NEW.grant_id
                ) <> (
                    SELECT app_id FROM applications_authorizationgroup
                    WHERE id = NEW.authorization_group_id
                ) THEN
                    RAISE EXCEPTION 'access grant group app mismatch';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER grants_access_grant_group_app_guard_insert
            BEFORE INSERT ON grants_accessgrantgroup
            FOR EACH ROW EXECUTE FUNCTION grants_access_grant_group_guard();
            CREATE TRIGGER grants_access_grant_group_app_guard_update
            BEFORE UPDATE OF grant_id, authorization_group_id ON grants_accessgrantgroup
            FOR EACH ROW EXECUTE FUNCTION grants_access_grant_group_guard();

            CREATE OR REPLACE FUNCTION grants_access_grant_permission_guard()
            RETURNS trigger AS $$
            BEGIN
                IF (
                    SELECT app_id FROM grants_accessgrant WHERE id = NEW.grant_id
                ) <> (
                    SELECT app_id FROM applications_permission WHERE id = NEW.permission_id
                ) THEN
                    RAISE EXCEPTION 'access grant permission app mismatch';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM applications_appscope app_scope
                    JOIN grants_accessgrant access_grant ON access_grant.id = NEW.grant_id
                    WHERE app_scope.app_id = access_grant.app_id
                      AND app_scope.key = NEW.scope_key
                ) THEN
                    RAISE EXCEPTION 'access grant permission scope app mismatch';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER grants_access_grant_permission_app_guard_insert
            BEFORE INSERT ON grants_accessgrantpermission
            FOR EACH ROW EXECUTE FUNCTION grants_access_grant_permission_guard();
            CREATE TRIGGER grants_access_grant_permission_app_guard_update
            BEFORE UPDATE OF grant_id, permission_id, scope_key ON grants_accessgrantpermission
            FOR EACH ROW EXECUTE FUNCTION grants_access_grant_permission_guard();
            """
        )


def drop_triggers(apps, schema_editor):
    del apps
    cursor = schema_editor.connection.cursor()
    if schema_editor.connection.vendor == "postgresql":
        cursor.execute(
            """
            DROP TRIGGER IF EXISTS grants_access_grant_permission_app_guard_update
              ON grants_accessgrantpermission;
            DROP TRIGGER IF EXISTS grants_access_grant_permission_app_guard_insert
              ON grants_accessgrantpermission;
            DROP FUNCTION IF EXISTS grants_access_grant_permission_guard();
            DROP TRIGGER IF EXISTS grants_access_grant_group_app_guard_update
              ON grants_accessgrantgroup;
            DROP TRIGGER IF EXISTS grants_access_grant_group_app_guard_insert
              ON grants_accessgrantgroup;
            DROP FUNCTION IF EXISTS grants_access_grant_group_guard();
            """
        )
        return
    if schema_editor.connection.vendor == "sqlite":
        cursor.executescript(
            """
            DROP TRIGGER IF EXISTS grants_access_grant_permission_app_guard_update;
            DROP TRIGGER IF EXISTS grants_access_grant_permission_app_guard_insert;
            DROP TRIGGER IF EXISTS grants_access_grant_group_app_guard_update;
            DROP TRIGGER IF EXISTS grants_access_grant_group_app_guard_insert;
            """
        )


class Migration(migrations.Migration):
    dependencies = [
        ("applications", "0029_managed_scope_policy_relationship_triggers"),
        ("grants", "0006_alter_accessgrant_user"),
    ]

    operations = [
        migrations.RunPython(assert_existing_relationships, migrations.RunPython.noop),
        migrations.RunPython(install_triggers, drop_triggers),
    ]
