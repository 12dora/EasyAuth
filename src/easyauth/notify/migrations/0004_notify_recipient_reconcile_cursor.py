from collections.abc import Sequence
from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("notify", "0003_freeze_notification_channel"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.AddField(
            model_name="notifyrecipient",
            name="dingtalk_source_slug",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
        migrations.AddField(
            model_name="notifyrecipient",
            name="last_reconciled_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
