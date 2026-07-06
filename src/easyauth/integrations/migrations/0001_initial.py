from collections.abc import Sequence
from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    initial: ClassVar[bool | None] = True

    dependencies: ClassVar[Sequence[tuple[str, str]]] = []

    operations: ClassVar[Sequence[Operation]] = [
        migrations.CreateModel(
            name="DingTalkStreamEvent",
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
                ("event_id", models.CharField(max_length=128, unique=True)),
                ("event_type", models.CharField(db_index=True, max_length=128)),
                ("corp_id", models.CharField(blank=True, default="", max_length=128)),
                ("born_at", models.DateTimeField(blank=True, null=True)),
                ("data", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("received", "received"),
                            ("processed", "processed"),
                            ("skipped", "skipped"),
                            ("failed", "failed"),
                        ],
                        db_index=True,
                        default="received",
                        max_length=16,
                    ),
                ),
                ("result", models.JSONField(blank=True, default=dict)),
                ("error", models.TextField(blank=True, default="")),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
