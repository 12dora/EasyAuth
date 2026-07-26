from __future__ import annotations

import django.db.models.deletion
from collections.abc import Sequence
from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("connectors", "0003_reconcile_fencing_constraints"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.CreateModel(
            name="ConnectorExternalGroup",
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
                ("external_ref", models.CharField(max_length=255)),
                ("external_name", models.CharField(max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "instance",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="external_groups",
                        to="connectors.connectorinstance",
                    ),
                ),
            ],
            options={
                "ordering": ["instance_id", "external_name", "external_ref"],
            },
        ),
        migrations.AddConstraint(
            model_name="connectorexternalgroup",
            constraint=models.UniqueConstraint(
                fields=("instance", "external_ref"),
                name="connectors_external_group_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="connectorexternalgroup",
            index=models.Index(
                fields=["instance", "is_active", "external_name", "external_ref"],
                name="connectors_ext_group_list_idx",
            ),
        ),
    ]
