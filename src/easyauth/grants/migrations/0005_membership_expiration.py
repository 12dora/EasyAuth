from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.apps.registry import Apps
    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
    from django.db.migrations.operations.base import Operation


def delete_parent_lifecycle_grants(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    _ = schema_editor
    AccessGrant = apps.get_model("grants", "AccessGrant")
    AccessGrant.objects.all().delete()


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("grants", "0004_delete_access_grant_role"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RunPython(delete_parent_lifecycle_grants, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="accessgrant",
            name="grants_access_grant_type_supported",
        ),
        migrations.RemoveConstraint(
            model_name="accessgrant",
            name="grants_access_grant_expiration_shape",
        ),
        migrations.RemoveField(model_name="accessgrant", name="grant_type"),
        migrations.RemoveField(model_name="accessgrant", name="grant_expires_at"),
        migrations.AddField(
            model_name="accessgrantgroup",
            name="expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="accessgrantpermission",
            name="expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
