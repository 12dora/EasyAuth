# ruff: noqa: ANN001, ANN201, ANN202, RUF012
# pyright: reportAny=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false, reportMissingParameterType=false, reportUnannotatedClassAttribute=false
from django.db import migrations


class AccessRequestRelationshipMigrationError(RuntimeError):
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
    raise AccessRequestRelationshipMigrationError(message)


def assert_existing_relationships(apps, schema_editor):
    del apps
    cursor = schema_editor.connection.cursor()
    _relation_blocker(
        cursor,
        label="AccessRequestGroup.authorization_group",
        count_sql="""
            SELECT COUNT(*), MIN(request_group.id), MAX(request_group.id)
            FROM access_requests_accessrequestgroup request_group
            JOIN access_requests_accessrequest access_request
              ON access_request.id = request_group.access_request_id
            JOIN applications_authorizationgroup auth_group
              ON auth_group.id = request_group.authorization_group_id
            WHERE access_request.app_id <> auth_group.app_id
        """,
        sample_sql="""
            SELECT request_group.id
            FROM access_requests_accessrequestgroup request_group
            JOIN access_requests_accessrequest access_request
              ON access_request.id = request_group.access_request_id
            JOIN applications_authorizationgroup auth_group
              ON auth_group.id = request_group.authorization_group_id
            WHERE access_request.app_id <> auth_group.app_id
            ORDER BY request_group.id
            LIMIT 20
        """,
    )
    _relation_blocker(
        cursor,
        label="AccessRequestPermission.permission",
        count_sql="""
            SELECT COUNT(*), MIN(request_permission.id), MAX(request_permission.id)
            FROM access_requests_accessrequestpermission request_permission
            JOIN access_requests_accessrequest access_request
              ON access_request.id = request_permission.access_request_id
            JOIN applications_permission permission
              ON permission.id = request_permission.permission_id
            WHERE access_request.app_id <> permission.app_id
        """,
        sample_sql="""
            SELECT request_permission.id
            FROM access_requests_accessrequestpermission request_permission
            JOIN access_requests_accessrequest access_request
              ON access_request.id = request_permission.access_request_id
            JOIN applications_permission permission
              ON permission.id = request_permission.permission_id
            WHERE access_request.app_id <> permission.app_id
            ORDER BY request_permission.id
            LIMIT 20
        """,
    )
    _relation_blocker(
        cursor,
        label="AccessRequestPermission.scope",
        count_sql="""
            SELECT COUNT(*), MIN(request_permission.id), MAX(request_permission.id)
            FROM access_requests_accessrequestpermission request_permission
            JOIN access_requests_accessrequest access_request
              ON access_request.id = request_permission.access_request_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM applications_appscope app_scope
                WHERE app_scope.app_id = access_request.app_id
                  AND app_scope.key = request_permission.scope_key
            )
        """,
        sample_sql="""
            SELECT request_permission.id
            FROM access_requests_accessrequestpermission request_permission
            JOIN access_requests_accessrequest access_request
              ON access_request.id = request_permission.access_request_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM applications_appscope app_scope
                WHERE app_scope.app_id = access_request.app_id
                  AND app_scope.key = request_permission.scope_key
            )
            ORDER BY request_permission.id
            LIMIT 20
        """,
    )


def install_triggers(apps, schema_editor):
    del apps
    cursor = schema_editor.connection.cursor()
    if schema_editor.connection.vendor == "sqlite":
        cursor.executescript(
            """
            CREATE TRIGGER access_request_group_app_guard_insert
            BEFORE INSERT ON access_requests_accessrequestgroup
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'access request group app mismatch')
                WHERE (
                    SELECT app_id FROM access_requests_accessrequest
                    WHERE id = NEW.access_request_id
                ) <> (
                    SELECT app_id FROM applications_authorizationgroup
                    WHERE id = NEW.authorization_group_id
                );
            END;
            CREATE TRIGGER access_request_group_app_guard_update
            BEFORE UPDATE OF access_request_id, authorization_group_id
            ON access_requests_accessrequestgroup
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'access request group app mismatch')
                WHERE (
                    SELECT app_id FROM access_requests_accessrequest
                    WHERE id = NEW.access_request_id
                ) <> (
                    SELECT app_id FROM applications_authorizationgroup
                    WHERE id = NEW.authorization_group_id
                );
            END;
            CREATE TRIGGER access_request_permission_app_guard_insert
            BEFORE INSERT ON access_requests_accessrequestpermission
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'access request permission app mismatch')
                WHERE (
                    SELECT app_id FROM access_requests_accessrequest
                    WHERE id = NEW.access_request_id
                ) <> (
                    SELECT app_id FROM applications_permission WHERE id = NEW.permission_id
                );
                SELECT RAISE(ABORT, 'access request permission scope app mismatch')
                WHERE NOT EXISTS (
                    SELECT 1 FROM applications_appscope app_scope
                    JOIN access_requests_accessrequest access_request
                      ON access_request.id = NEW.access_request_id
                    WHERE app_scope.app_id = access_request.app_id
                      AND app_scope.key = NEW.scope_key
                );
            END;
            CREATE TRIGGER access_request_permission_app_guard_update
            BEFORE UPDATE OF access_request_id, permission_id, scope_key
            ON access_requests_accessrequestpermission
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'access request permission app mismatch')
                WHERE (
                    SELECT app_id FROM access_requests_accessrequest
                    WHERE id = NEW.access_request_id
                ) <> (
                    SELECT app_id FROM applications_permission WHERE id = NEW.permission_id
                );
                SELECT RAISE(ABORT, 'access request permission scope app mismatch')
                WHERE NOT EXISTS (
                    SELECT 1 FROM applications_appscope app_scope
                    JOIN access_requests_accessrequest access_request
                      ON access_request.id = NEW.access_request_id
                    WHERE app_scope.app_id = access_request.app_id
                      AND app_scope.key = NEW.scope_key
                );
            END;
            """
        )
        return
    if schema_editor.connection.vendor == "postgresql":
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION access_request_group_guard()
            RETURNS trigger AS $$
            BEGIN
                IF (
                    SELECT app_id FROM access_requests_accessrequest
                    WHERE id = NEW.access_request_id
                ) <> (
                    SELECT app_id FROM applications_authorizationgroup
                    WHERE id = NEW.authorization_group_id
                ) THEN
                    RAISE EXCEPTION 'access request group app mismatch';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER access_request_group_app_guard_insert
            BEFORE INSERT ON access_requests_accessrequestgroup
            FOR EACH ROW EXECUTE FUNCTION access_request_group_guard();
            CREATE TRIGGER access_request_group_app_guard_update
            BEFORE UPDATE OF access_request_id, authorization_group_id
            ON access_requests_accessrequestgroup
            FOR EACH ROW EXECUTE FUNCTION access_request_group_guard();

            CREATE OR REPLACE FUNCTION access_request_permission_guard()
            RETURNS trigger AS $$
            BEGIN
                IF (
                    SELECT app_id FROM access_requests_accessrequest
                    WHERE id = NEW.access_request_id
                ) <> (
                    SELECT app_id FROM applications_permission WHERE id = NEW.permission_id
                ) THEN
                    RAISE EXCEPTION 'access request permission app mismatch';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM applications_appscope app_scope
                    JOIN access_requests_accessrequest access_request
                      ON access_request.id = NEW.access_request_id
                    WHERE app_scope.app_id = access_request.app_id
                      AND app_scope.key = NEW.scope_key
                ) THEN
                    RAISE EXCEPTION 'access request permission scope app mismatch';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER access_request_permission_app_guard_insert
            BEFORE INSERT ON access_requests_accessrequestpermission
            FOR EACH ROW EXECUTE FUNCTION access_request_permission_guard();
            CREATE TRIGGER access_request_permission_app_guard_update
            BEFORE UPDATE OF access_request_id, permission_id, scope_key
            ON access_requests_accessrequestpermission
            FOR EACH ROW EXECUTE FUNCTION access_request_permission_guard();
            """
        )


def drop_triggers(apps, schema_editor):
    del apps
    cursor = schema_editor.connection.cursor()
    if schema_editor.connection.vendor == "postgresql":
        cursor.execute(
            """
            DROP TRIGGER IF EXISTS access_request_permission_app_guard_update
              ON access_requests_accessrequestpermission;
            DROP TRIGGER IF EXISTS access_request_permission_app_guard_insert
              ON access_requests_accessrequestpermission;
            DROP FUNCTION IF EXISTS access_request_permission_guard();
            DROP TRIGGER IF EXISTS access_request_group_app_guard_update
              ON access_requests_accessrequestgroup;
            DROP TRIGGER IF EXISTS access_request_group_app_guard_insert
              ON access_requests_accessrequestgroup;
            DROP FUNCTION IF EXISTS access_request_group_guard();
            """
        )
        return
    if schema_editor.connection.vendor == "sqlite":
        cursor.executescript(
            """
            DROP TRIGGER IF EXISTS access_request_permission_app_guard_update;
            DROP TRIGGER IF EXISTS access_request_permission_app_guard_insert;
            DROP TRIGGER IF EXISTS access_request_group_app_guard_update;
            DROP TRIGGER IF EXISTS access_request_group_app_guard_insert;
            """
        )


class Migration(migrations.Migration):
    dependencies = [
        ("access_requests", "0013_accessrequestgroupgrantsnapshot_and_more"),
        ("applications", "0029_managed_scope_policy_relationship_triggers"),
    ]

    operations = [
        migrations.RunPython(assert_existing_relationships, migrations.RunPython.noop),
        migrations.RunPython(install_triggers, drop_triggers),
    ]
