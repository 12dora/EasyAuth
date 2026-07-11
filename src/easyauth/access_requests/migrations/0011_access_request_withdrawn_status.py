from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("access_requests", "0010_normalize_request_approvers"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
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
                    ("withdrawn", "withdrawn"),
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
                        "withdrawn",
                    ),
                ),
                name="access_requests_status_supported",
            ),
        ),
    ]
