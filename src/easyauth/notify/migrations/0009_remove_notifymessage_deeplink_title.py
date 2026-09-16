# 工作通知已改为钉钉 OA, 不再存储 action_card 按钮文案。

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("notify", "0008_oa_message_fields"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RemoveField(
            model_name="notifymessage",
            name="deeplink_title",
        ),
    ]
