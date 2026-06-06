from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("access_requests", "0002_ops4_renew_request_type"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.AddField(
            model_name="accessrequest",
            name="dingtalk_process_instance_id",
            field=models.CharField(blank=True, max_length=128, null=True, unique=True),
        ),
    ]
