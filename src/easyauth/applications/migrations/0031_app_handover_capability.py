# 交接能力三态声明(01 §2.7)

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("applications", "0030_dependency_health_retention_index"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.AddField(
            model_name="app",
            name="handover_capability",
            field=models.CharField(
                choices=[
                    ("declared", "declared"),
                    ("none", "none"),
                    ("undeclared", "undeclared"),
                ],
                default="undeclared",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="app",
            name="handover_asset_types",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="app",
            name="handover_capability_declared_by",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="app",
            name="handover_capability_declared_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="app",
            name="handover_capability_synced_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="app",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    handover_capability__in=("declared", "none", "undeclared"),
                ),
                name="applications_app_handover_capability_supported",
            ),
        ),
        migrations.AddConstraint(
            model_name="app",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        handover_capability="none",
                        handover_capability_declared_by__gt="",
                        handover_capability_declared_at__isnull=False,
                    )
                    | ~models.Q(handover_capability="none")
                ),
                name="applications_app_handover_none_requires_declaration",
            ),
        ),
    ]
