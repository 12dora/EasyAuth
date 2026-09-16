# 公司级工作通知改走独立钉钉应用(服务号), 与目录同步/Stream/登录主应用分离。

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import easyauth.config.crypto
from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("applications", "0034_backfill_builtin_super_admin"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.AddField(
            model_name="integrationsettings",
            name="dingtalk_notify_app_key",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="integrationsettings",
            name="dingtalk_notify_app_secret",
            field=easyauth.config.crypto.EncryptedCharField(blank=True, max_length=1024),
        ),
        migrations.AddField(
            model_name="integrationsettings",
            name="dingtalk_notify_agent_id",
            field=models.CharField(blank=True, max_length=64),
        ),
    ]
