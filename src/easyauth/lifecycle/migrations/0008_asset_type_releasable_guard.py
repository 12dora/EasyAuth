# 数据交接 v2：父资产类型变更时复核 override 的可释放性。

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.apps.registry import Apps
    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
    from django.db.migrations.operations.base import Operation


def install_asset_type_releasable_guard(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    _ = apps
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION lifecycle_check_asset_type_releasable()
            RETURNS trigger AS $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM lifecycle_handoverassettype AS asset_type
                    JOIN lifecycle_handoverassetoverride AS override
                      ON override.asset_type_id = asset_type.id
                    WHERE asset_type.id = NEW.id
                      AND asset_type.releasable IS FALSE
                      AND override.action = 'release'
                ) THEN
                    RAISE EXCEPTION
                        'lifecycle_override_release_requires_releasable: parent asset type is not releasable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """,
        )
        cursor.execute(
            """
            CREATE CONSTRAINT TRIGGER lifecycle_asset_type_releasable_trg
            AFTER UPDATE OF releasable ON lifecycle_handoverassettype
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION lifecycle_check_asset_type_releasable();
            """,
        )


def drop_asset_type_releasable_guard(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    _ = apps
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS lifecycle_asset_type_releasable_trg "
            "ON lifecycle_handoverassettype;",
        )
        cursor.execute("DROP FUNCTION IF EXISTS lifecycle_check_asset_type_releasable();")


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("lifecycle", "0007_a1c_handover_api_approvals"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RunPython(
            install_asset_type_releasable_guard,
            drop_asset_type_releasable_guard,
        ),
    ]
