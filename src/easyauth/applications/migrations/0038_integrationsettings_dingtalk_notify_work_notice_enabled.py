# 工作通知(OA)渠道的全局开关, 默认开启。

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("applications", "0037_integrationsettings_dingtalk_notify_robot_enabled"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.AddField(
            model_name="integrationsettings",
            name="dingtalk_notify_work_notice_enabled",
            field=models.BooleanField(default=True),
        ),
    ]
