from __future__ import annotations

# ruff: noqa: TC002, TC003
from collections.abc import Sequence
from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("applications", "0007_role_access_policy"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RemoveConstraint(
            model_name="dependencyhealthsnapshot",
            name="applications_dependency_health_dependency_supported",
        ),
        migrations.AlterField(
            model_name="dependencyhealthsnapshot",
            name="dependency",
            field=models.CharField(
                choices=[
                    ("authentik", "authentik"),
                    ("authentik_directory", "authentik_directory"),
                    ("dingtalk", "dingtalk"),
                    ("celery", "celery"),
                ],
                max_length=64,
            ),
        ),
        migrations.AddConstraint(
            model_name="dependencyhealthsnapshot",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "dependency__in",
                        ("authentik", "authentik_directory", "dingtalk", "celery"),
                    ),
                ),
                name="applications_dependency_health_dependency_supported",
            ),
        ),
    ]
