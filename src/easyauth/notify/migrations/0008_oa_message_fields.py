# 工作通知改为钉钉 OA; 落库表单字段、展示名覆盖与发送者。

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


def _rewrite_templates_to_oa(apps: object, _schema_editor: object) -> None:
    notify_message = apps.get_model("notify", "NotifyMessage")  # type: ignore[attr-defined]
    _ = notify_message.objects.exclude(template="oa").update(template="oa")


def _restore_oa_templates_to_markdown(apps: object, _schema_editor: object) -> None:
    # 正向把历史 text/markdown/action_card 一律写成 oa, 无法还原原始类型。
    # 回滚只能把 oa 映回 markdown, 使旧 choices 合法; 这是不可逆的数据近似。
    notify_message = apps.get_model("notify", "NotifyMessage")  # type: ignore[attr-defined]
    _ = notify_message.objects.filter(template="oa").update(template="markdown")


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("notify", "0007_remove_legacy_recipient_identity"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.AddField(
            model_name="notifymessage",
            name="form_fields",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="notifymessage",
            name="app_display_name",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="notifymessage",
            name="author",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.RunPython(_rewrite_templates_to_oa, _restore_oa_templates_to_markdown),
        migrations.AlterField(
            model_name="notifymessage",
            name="template",
            field=models.CharField(
                choices=[("oa", "oa")],
                default="oa",
                max_length=16,
            ),
        ),
    ]
