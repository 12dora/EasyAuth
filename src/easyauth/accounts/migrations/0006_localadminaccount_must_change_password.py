from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("accounts", "0005_localadminaccount_localadminpasskey"),
    ]

    # 默认 True: 存量本地管理员下次登录也会被强制修改密码(预期行为)。
    operations: ClassVar[Sequence[Operation]] = [
        migrations.AddField(
            model_name="localadminaccount",
            name="must_change_password",
            field=models.BooleanField(default=True),
        ),
    ]
