# 控制台维护的应用别名; manifest 推送不得覆盖。

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("applications", "0032_app_descriptor_base_url_app_descriptor_token"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.AddField(
            model_name="app",
            name="alias",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
    ]
