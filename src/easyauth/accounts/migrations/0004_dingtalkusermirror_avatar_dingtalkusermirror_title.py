from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("accounts", "0003_user_mirror_avatar_url"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.AddField(
            model_name="dingtalkusermirror",
            name="avatar",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="dingtalkusermirror",
            name="title",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
    ]
