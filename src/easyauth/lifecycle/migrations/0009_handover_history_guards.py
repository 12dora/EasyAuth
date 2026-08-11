# 数据交接 v2：投递与强行跳过史料只允许契约规定的变更。

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.apps.registry import Apps
    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
    from django.db.migrations.operations.base import Operation


def install_handover_history_guards(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    _ = apps
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION lifecycle_guard_delivery_transition()
            RETURNS trigger AS $$
            BEGIN
                IF OLD.outcome <> 'sent' THEN
                    RAISE EXCEPTION
                        'lifecycle_delivery_terminal_immutable: terminal delivery cannot be modified';
                END IF;
                IF NEW.outcome NOT IN ('succeeded', 'failed', 'async_accepted', 'superseded') THEN
                    RAISE EXCEPTION
                        'lifecycle_delivery_transition_invalid: sent delivery must transition to a terminal outcome';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """,
        )
        cursor.execute(
            """
            CREATE TRIGGER lifecycle_delivery_transition_guard_trg
            BEFORE UPDATE ON lifecycle_handoverdeliveryattempt
            FOR EACH ROW EXECUTE FUNCTION lifecycle_guard_delivery_transition();
            """,
        )
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION lifecycle_guard_skip_record_immutable()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION
                    'lifecycle_skip_record_immutable: skip history cannot be updated or deleted';
            END;
            $$ LANGUAGE plpgsql;
            """,
        )
        cursor.execute(
            """
            CREATE TRIGGER lifecycle_skip_record_immutable_trg
            BEFORE UPDATE OR DELETE ON lifecycle_handoveractionskiprecord
            FOR EACH ROW EXECUTE FUNCTION lifecycle_guard_skip_record_immutable();
            """,
        )
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION lifecycle_guard_task_skip_history()
            RETURNS trigger AS $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM lifecycle_handoveractionskiprecord
                    WHERE task_id_snapshot = OLD.id
                ) THEN
                    RAISE EXCEPTION
                        'lifecycle_task_has_skip_history: task with skip history cannot be deleted';
                END IF;
                RETURN OLD;
            END;
            $$ LANGUAGE plpgsql;
            """,
        )
        cursor.execute(
            """
            CREATE TRIGGER lifecycle_task_skip_history_guard_trg
            BEFORE DELETE ON lifecycle_handovertask
            FOR EACH ROW EXECUTE FUNCTION lifecycle_guard_task_skip_history();
            """,
        )


def drop_handover_history_guards(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    _ = apps
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS lifecycle_task_skip_history_guard_trg "
            "ON lifecycle_handovertask;",
        )
        cursor.execute("DROP FUNCTION IF EXISTS lifecycle_guard_task_skip_history();")
        cursor.execute(
            "DROP TRIGGER IF EXISTS lifecycle_skip_record_immutable_trg "
            "ON lifecycle_handoveractionskiprecord;",
        )
        cursor.execute("DROP FUNCTION IF EXISTS lifecycle_guard_skip_record_immutable();")
        cursor.execute(
            "DROP TRIGGER IF EXISTS lifecycle_delivery_transition_guard_trg "
            "ON lifecycle_handoverdeliveryattempt;",
        )
        cursor.execute("DROP FUNCTION IF EXISTS lifecycle_guard_delivery_transition();")


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("lifecycle", "0008_asset_type_releasable_guard"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RunPython(
            install_handover_history_guards,
            drop_handover_history_guards,
        ),
    ]
