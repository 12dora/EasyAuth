from collections.abc import Sequence
from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("notify", "0003_freeze_notification_channel"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        # 0003 的原子事务先完成历史消息回填并提交。将 NOT NULL 放到下一迁移，
        # 避免 PostgreSQL 在同一事务仍有 FK pending trigger events 时 ALTER TABLE。
        migrations.AlterField(
            model_name="notifymessage",
            name="channel",
            field=models.ForeignKey(
                on_delete=models.deletion.PROTECT,
                related_name="notify_messages",
                to="applications.appnotificationchannel",
            ),
        ),
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
