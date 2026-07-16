from collections.abc import Sequence
from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("notify", "0004_notify_recipient_reconcile_cursor"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.AlterField(
            model_name="notifyrecipient",
            name="raw_ref",
            field=models.CharField(max_length=4096),
        ),
        migrations.RemoveConstraint(
            model_name="notifyrecipient",
            name="notify_recipient_target_unique",
        ),
        migrations.AddConstraint(
            model_name="notifyrecipient",
            constraint=models.UniqueConstraint(
                condition=(
                    ~models.Q(dingtalk_userid="")
                    & ~models.Q(dingtalk_source_slug="")
                    & ~models.Q(dingtalk_corp_id="")
                ),
                fields=(
                    "message",
                    "dingtalk_source_slug",
                    "dingtalk_corp_id",
                    "dingtalk_userid",
                ),
                name="notify_recipient_scoped_target_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="notifyrecipient",
            constraint=models.UniqueConstraint(
                condition=(
                    ~models.Q(dingtalk_userid="")
                    & (models.Q(dingtalk_source_slug="") | models.Q(dingtalk_corp_id=""))
                ),
                fields=("message", "dingtalk_userid"),
                name="notify_recipient_legacy_target_unique",
            ),
        ),
    ]
