from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("access_requests", "0001_initial"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RemoveConstraint(
            model_name="accessrequest",
            name="access_requests_request_type_supported",
        ),
        migrations.AlterField(
            model_name="accessrequest",
            name="request_type",
            field=models.CharField(
                choices=[
                    ("grant", "grant"),
                    ("change", "change"),
                    ("revoke", "revoke"),
                    ("renew", "renew"),
                ],
                default="grant",
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="accessrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(("request_type__in", ("grant", "change", "revoke", "renew"))),
                name="access_requests_request_type_supported",
            ),
        ),
    ]
