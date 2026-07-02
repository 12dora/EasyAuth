from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("access_requests", "0004_scoped_targets"),
    ]

    operations: ClassVar[list[migrations.operations.base.Operation]] = [
        migrations.AddField(
            model_name="accessrequest",
            name="approver_user_ids",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
