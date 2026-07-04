
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import django.db.models.deletion
from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):

    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("applications", "0006_dependency_health_snapshot"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.CreateModel(
            name="RoleAccessPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_high_risk", models.BooleanField(default=False)),
                ("max_grant_duration_days", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("role", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="access_policies", to="applications.role")),
            ],
            options={
                "ordering": ["role__app__app_key", "role__key"],
                "constraints": [
                    models.UniqueConstraint(fields=("role",), name="applications_role_access_policy_unique"),
                    models.CheckConstraint(condition=(models.Q(("max_grant_duration_days__isnull", True)) | models.Q(("max_grant_duration_days__gte", 1))), name="applications_role_access_policy_max_duration_positive"),
                    models.CheckConstraint(condition=(models.Q(("is_high_risk", True), ("max_grant_duration_days__isnull", False)) | models.Q(("is_high_risk", False), ("max_grant_duration_days__isnull", True))), name="applications_role_access_policy_high_risk_shape"),
                ],
            },
        ),
    ]
