from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.apps.registry import Apps
    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
    from django.db.migrations.operations.base import Operation


def delete_pre_idempotency_requests(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    _ = schema_editor
    AccessRequest = apps.get_model("access_requests", "AccessRequest")
    AccessRequest.objects.all().delete()


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("access_requests", "0008_delete_access_request_role"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RunPython(delete_pre_idempotency_requests, migrations.RunPython.noop),
        migrations.AddField(
            model_name="accessrequest",
            name="idempotency_key",
            field=models.CharField(max_length=128),
        ),
        migrations.AddField(
            model_name="accessrequest",
            name="payload_digest",
            field=models.CharField(editable=False, max_length=64),
        ),
        migrations.RemoveConstraint(
            model_name="accessrequest",
            name="access_requests_status_supported",
        ),
        migrations.AlterField(
            model_name="accessrequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("submitted", "submitted"),
                    ("approved", "approved"),
                    ("rejected", "rejected"),
                    ("grant_applied", "grant_applied"),
                    ("grant_failed", "grant_failed"),
                    ("grant_expired", "grant_expired"),
                ],
                default="submitted",
                max_length=32,
            ),
        ),
        migrations.AddConstraint(
            model_name="accessrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "submitted",
                        "approved",
                        "rejected",
                        "grant_applied",
                        "grant_failed",
                        "grant_expired",
                    ),
                ),
                name="access_requests_status_supported",
            ),
        ),
        migrations.AddConstraint(
            model_name="accessrequest",
            constraint=models.UniqueConstraint(
                fields=("user", "idempotency_key"),
                name="access_requests_user_idempotency_key_unique",
            ),
        ),
    ]
