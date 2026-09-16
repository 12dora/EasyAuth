# 收件人增加服务号机器人 sidecar 投递结果, 与工作通知状态机独立。

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("notify", "0009_remove_notifymessage_deeplink_title"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.AddField(
            model_name="notifyrecipient",
            name="robot_process_query_key",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.AddField(
            model_name="notifyrecipient",
            name="robot_status",
            field=models.CharField(
                blank=True,
                choices=[("sent", "sent"), ("failed", "failed")],
                max_length=16,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="notifyrecipient",
            name="robot_error",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="notifyrecipient",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(robot_status__isnull=True)
                    | models.Q(robot_status__in=("sent", "failed"))
                ),
                name="notify_recipient_robot_status_supported",
            ),
        ),
        migrations.AddConstraint(
            model_name="notifyrecipient",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(robot_status__isnull=True)
                    | models.Q(robot_status="failed")
                    | (
                        models.Q(robot_status="sent")
                        & models.Q(robot_process_query_key__isnull=False)
                        & ~models.Q(robot_process_query_key="")
                    )
                ),
                name="notify_recipient_robot_sent_shape",
            ),
        ),
        migrations.AddConstraint(
            model_name="notifyrecipient",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(robot_status__isnull=True)
                    | models.Q(robot_status="sent")
                    | (
                        models.Q(robot_status="failed")
                        & models.Q(robot_error__isnull=False)
                        & ~models.Q(robot_error="")
                    )
                ),
                name="notify_recipient_robot_failed_shape",
            ),
        ),
    ]
