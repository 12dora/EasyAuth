# ruff: noqa: E501

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):

    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("applications", "0005_ops1_configuration_models"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.CreateModel(
            name="DependencyHealthSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("dependency", models.CharField(choices=[("authentik", "authentik"), ("dingtalk", "dingtalk"), ("celery", "celery")], max_length=64)),
                ("status", models.CharField(choices=[("healthy", "healthy"), ("warning", "warning"), ("unhealthy", "unhealthy"), ("unknown", "unknown")], default="unknown", max_length=32)),
                ("checked_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("summary", models.TextField(blank=True)),
                ("error_summary", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("app", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="dependency_health_snapshots", to="applications.app")),
            ],
            options={
                "ordering": ["dependency", "-checked_at", "-id"],
                "indexes": [models.Index(fields=["dependency", "-checked_at", "-id"], name="app_dep_health_latest_idx")],
                "constraints": [
                    models.CheckConstraint(condition=models.Q(("dependency__in", ("authentik", "dingtalk", "celery"))), name="applications_dependency_health_dependency_supported"),
                    models.CheckConstraint(condition=models.Q(("status__in", ("healthy", "warning", "unhealthy", "unknown"))), name="applications_dependency_health_status_supported"),
                ],
            },
        ),
    ]
