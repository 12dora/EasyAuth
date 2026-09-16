# 应用登记可选工作通知 OA 头色带。

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("applications", "0035_integrationsettings_dingtalk_notify_credentials"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.AddField(
            model_name="app",
            name="notify_head_bgcolor",
            field=models.CharField(blank=True, default="", max_length=8),
        ),
    ]
