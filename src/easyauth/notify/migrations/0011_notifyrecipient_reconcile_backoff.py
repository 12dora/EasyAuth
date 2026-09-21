# 回执对账增加尝试次数与下次轮询时间, 限制钉钉计费调用。

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("notify", "0010_notifyrecipient_robot_delivery"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.AddField(
            model_name="notifyrecipient",
            name="reconcile_attempts",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="notifyrecipient",
            name="next_reconcile_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
