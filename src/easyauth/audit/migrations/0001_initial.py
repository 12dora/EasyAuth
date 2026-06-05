from collections.abc import Sequence
from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    initial: ClassVar[bool | None] = True

    dependencies: ClassVar[Sequence[tuple[str, str]]] = []

    operations: ClassVar[Sequence[Operation]] = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("actor_type", models.CharField(max_length=32)),
                ("actor_id", models.CharField(max_length=128)),
                ("event_type", models.CharField(max_length=128)),
                ("target_type", models.CharField(max_length=64)),
                ("target_id", models.CharField(max_length=128)),
                ("metadata", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]
