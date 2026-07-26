# ruff: noqa: ANN001, ANN201, ANN202, RUF012
# pyright: reportAny=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportMissingParameterType=false, reportUnannotatedClassAttribute=false
from django.db import migrations


class ApplicationRelationshipMigrationError(RuntimeError):
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
    raise ApplicationRelationshipMigrationError(message)


def assert_existing_relationships(apps, schema_editor):
    del apps
    cursor = schema_editor.connection.cursor()
    _relation_blocker(
        cursor,
        label="AuthorizationGroupGrant.permission",
        count_sql="""
            SELECT COUNT(*), MIN(auth_group_grant.id), MAX(auth_group_grant.id)
            FROM applications_authorizationgroupgrant auth_group_grant
            JOIN applications_authorizationgroup auth_group
              ON auth_group.id = auth_group_grant.authorization_group_id
            JOIN applications_permission permission
              ON permission.id = auth_group_grant.permission_id
            WHERE auth_group.app_id <> permission.app_id
        """,
        sample_sql="""
            SELECT auth_group_grant.id
            FROM applications_authorizationgroupgrant auth_group_grant
            JOIN applications_authorizationgroup auth_group
              ON auth_group.id = auth_group_grant.authorization_group_id
            JOIN applications_permission permission
              ON permission.id = auth_group_grant.permission_id
            WHERE auth_group.app_id <> permission.app_id
            ORDER BY auth_group_grant.id
            LIMIT 20
        """,
    )
    _relation_blocker(
        cursor,
        label="AuthorizationGroupGrant.scope",
        count_sql="""
            SELECT COUNT(*), MIN(auth_group_grant.id), MAX(auth_group_grant.id)
            FROM applications_authorizationgroupgrant auth_group_grant
            JOIN applications_authorizationgroup auth_group
              ON auth_group.id = auth_group_grant.authorization_group_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM applications_appscope app_scope
                WHERE app_scope.app_id = auth_group.app_id
                  AND app_scope.key = auth_group_grant.scope_key
            )
        """,
        sample_sql="""
            SELECT auth_group_grant.id
            FROM applications_authorizationgroupgrant auth_group_grant
            JOIN applications_authorizationgroup auth_group
              ON auth_group.id = auth_group_grant.authorization_group_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM applications_appscope app_scope
                WHERE app_scope.app_id = auth_group.app_id
                  AND app_scope.key = auth_group_grant.scope_key
            )
            ORDER BY auth_group_grant.id
            LIMIT 20
        """,
    )
    _relation_blocker(
        cursor,
        label="ManagedScopePolicy.authorization_group_grant",
        count_sql="""
            SELECT COUNT(*), MIN(policy.id), MAX(policy.id)
            FROM applications_managedscopepolicy policy
            JOIN applications_authorizationgroupgrant auth_group_grant
              ON auth_group_grant.id = policy.authorization_group_grant_id
            JOIN applications_authorizationgroup auth_group
              ON auth_group.id = auth_group_grant.authorization_group_id
            WHERE policy.authorization_group_grant_id IS NOT NULL
              AND policy.app_id <> auth_group.app_id
        """,
        sample_sql="""
            SELECT policy.id
            FROM applications_managedscopepolicy policy
            JOIN applications_authorizationgroupgrant auth_group_grant
              ON auth_group_grant.id = policy.authorization_group_grant_id
            JOIN applications_authorizationgroup auth_group
              ON auth_group.id = auth_group_grant.authorization_group_id
            WHERE policy.authorization_group_grant_id IS NOT NULL
              AND policy.app_id <> auth_group.app_id
            ORDER BY policy.id
            LIMIT 20
        """,
    )


def install_triggers(apps, schema_editor):
    del apps
    vendor = schema_editor.connection.vendor
    cursor = schema_editor.connection.cursor()
    if vendor == "sqlite":
        cursor.executescript(
            """
            CREATE TRIGGER applications_auth_group_grant_app_guard_insert
            BEFORE INSERT ON applications_authorizationgroupgrant
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'authorization group grant permission app mismatch')
                WHERE (
                    SELECT app_id FROM applications_authorizationgroup
                    WHERE id = NEW.authorization_group_id
                ) <> (
                    SELECT app_id FROM applications_permission
                    WHERE id = NEW.permission_id
                );
                SELECT RAISE(ABORT, 'authorization group grant scope app mismatch')
                WHERE NOT EXISTS (
                    SELECT 1 FROM applications_appscope app_scope
                    JOIN applications_authorizationgroup auth_group
                      ON auth_group.id = NEW.authorization_group_id
                    WHERE app_scope.app_id = auth_group.app_id AND app_scope.key = NEW.scope_key
                );
            END;
            CREATE TRIGGER applications_auth_group_grant_app_guard_update
            BEFORE UPDATE OF authorization_group_id, permission_id, scope_key
            ON applications_authorizationgroupgrant
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'authorization group grant permission app mismatch')
                WHERE (
                    SELECT app_id FROM applications_authorizationgroup
                    WHERE id = NEW.authorization_group_id
                ) <> (
                    SELECT app_id FROM applications_permission
                    WHERE id = NEW.permission_id
                );
                SELECT RAISE(ABORT, 'authorization group grant scope app mismatch')
                WHERE NOT EXISTS (
                    SELECT 1 FROM applications_appscope app_scope
                    JOIN applications_authorizationgroup auth_group
                      ON auth_group.id = NEW.authorization_group_id
                    WHERE app_scope.app_id = auth_group.app_id AND app_scope.key = NEW.scope_key
                );
            END;
            CREATE TRIGGER applications_managed_scope_policy_grant_guard_insert
            BEFORE INSERT ON applications_managedscopepolicy
            FOR EACH ROW
            WHEN NEW.authorization_group_grant_id IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, 'managed scope policy grant app mismatch')
                WHERE NEW.app_id <> (
                    SELECT auth_group.app_id
                    FROM applications_authorizationgroupgrant auth_group_grant
                    JOIN applications_authorizationgroup auth_group
                      ON auth_group.id = auth_group_grant.authorization_group_id
                    WHERE auth_group_grant.id = NEW.authorization_group_grant_id
                );
            END;
            CREATE TRIGGER applications_managed_scope_policy_grant_guard_update
            BEFORE UPDATE OF app_id, authorization_group_grant_id
            ON applications_managedscopepolicy
            FOR EACH ROW
            WHEN NEW.authorization_group_grant_id IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, 'managed scope policy grant app mismatch')
                WHERE NEW.app_id <> (
                    SELECT auth_group.app_id
                    FROM applications_authorizationgroupgrant auth_group_grant
                    JOIN applications_authorizationgroup auth_group
                      ON auth_group.id = auth_group_grant.authorization_group_id
                    WHERE auth_group_grant.id = NEW.authorization_group_grant_id
                );
            END;
            """
        )
        return
    if vendor == "postgresql":
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION applications_auth_group_grant_guard()
            RETURNS trigger AS $$
            BEGIN
                IF (
                    SELECT app_id FROM applications_authorizationgroup
                    WHERE id = NEW.authorization_group_id
                ) <> (
                    SELECT app_id FROM applications_permission
                    WHERE id = NEW.permission_id
                ) THEN
                    RAISE EXCEPTION 'authorization group grant permission app mismatch';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM applications_appscope app_scope
                    JOIN applications_authorizationgroup auth_group
                      ON auth_group.id = NEW.authorization_group_id
                    WHERE app_scope.app_id = auth_group.app_id AND app_scope.key = NEW.scope_key
                ) THEN
                    RAISE EXCEPTION 'authorization group grant scope app mismatch';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER applications_auth_group_grant_app_guard_insert
            BEFORE INSERT ON applications_authorizationgroupgrant
            FOR EACH ROW EXECUTE FUNCTION applications_auth_group_grant_guard();
            CREATE TRIGGER applications_auth_group_grant_app_guard_update
            BEFORE UPDATE OF authorization_group_id, permission_id, scope_key
            ON applications_authorizationgroupgrant
            FOR EACH ROW EXECUTE FUNCTION applications_auth_group_grant_guard();

            CREATE OR REPLACE FUNCTION applications_managed_scope_policy_grant_guard()
            RETURNS trigger AS $$
            BEGIN
                IF NEW.authorization_group_grant_id IS NOT NULL AND NEW.app_id <> (
                    SELECT auth_group.app_id
                    FROM applications_authorizationgroupgrant auth_group_grant
                    JOIN applications_authorizationgroup auth_group
                      ON auth_group.id = auth_group_grant.authorization_group_id
                    WHERE auth_group_grant.id = NEW.authorization_group_grant_id
                ) THEN
                    RAISE EXCEPTION 'managed scope policy grant app mismatch';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER applications_managed_scope_policy_grant_guard_insert
            BEFORE INSERT ON applications_managedscopepolicy
            FOR EACH ROW EXECUTE FUNCTION applications_managed_scope_policy_grant_guard();
            CREATE TRIGGER applications_managed_scope_policy_grant_guard_update
            BEFORE UPDATE OF app_id, authorization_group_grant_id
            ON applications_managedscopepolicy
            FOR EACH ROW EXECUTE FUNCTION applications_managed_scope_policy_grant_guard();
            """
        )


def drop_triggers(apps, schema_editor):
    del apps
    cursor = schema_editor.connection.cursor()
    if schema_editor.connection.vendor == "postgresql":
        cursor.execute(
            """
            DROP TRIGGER IF EXISTS applications_managed_scope_policy_grant_guard_update
              ON applications_managedscopepolicy;
            DROP TRIGGER IF EXISTS applications_managed_scope_policy_grant_guard_insert
              ON applications_managedscopepolicy;
            DROP FUNCTION IF EXISTS applications_managed_scope_policy_grant_guard();
            DROP TRIGGER IF EXISTS applications_auth_group_grant_app_guard_update
              ON applications_authorizationgroupgrant;
            DROP TRIGGER IF EXISTS applications_auth_group_grant_app_guard_insert
              ON applications_authorizationgroupgrant;
            DROP FUNCTION IF EXISTS applications_auth_group_grant_guard();
            """
        )
        return
    if schema_editor.connection.vendor == "sqlite":
        cursor.executescript(
            """
            DROP TRIGGER IF EXISTS applications_managed_scope_policy_grant_guard_update;
            DROP TRIGGER IF EXISTS applications_managed_scope_policy_grant_guard_insert;
            DROP TRIGGER IF EXISTS applications_auth_group_grant_app_guard_update;
            DROP TRIGGER IF EXISTS applications_auth_group_grant_app_guard_insert;
            """
        )


class Migration(migrations.Migration):
    dependencies = [
        ("applications", "0028_alter_managedscopepolicy_options_and_more"),
    ]

    operations = [
        migrations.RunPython(assert_existing_relationships, migrations.RunPython.noop),
        migrations.RunPython(install_triggers, drop_triggers),
    ]
