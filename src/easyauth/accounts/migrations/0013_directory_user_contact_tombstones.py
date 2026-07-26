from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol, cast

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
    from django.db.migrations.operations.base import Operation
    from django.db.migrations.state import StateApps

_SUPPORTED_DINGTALK_STATUSES = ("active", "disabled", "departed")


class _MigrationQuerySet(Protocol):
    def order_by(self, *field_names: str) -> _MigrationQuerySet: ...

    def count(self) -> int: ...

    def values_list(self, field_name: str, *, flat: bool = False) -> Sequence[int]: ...


class _MigrationManager(Protocol):
    def exclude(self, **kwargs: object) -> _MigrationQuerySet: ...


class _HistoricalDingTalkUserMirror(Protocol):
    objects: _MigrationManager


def assert_supported_directory_status(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    _ = schema_editor
    mirror = apps.get_model("accounts", "DingTalkUserMirror")
    dingtalk_user_mirror = cast("_HistoricalDingTalkUserMirror", mirror)
    queryset = dingtalk_user_mirror.objects.exclude(
        status__in=_SUPPORTED_DINGTALK_STATUSES,
    ).order_by("id")
    count = queryset.count()
    if count:
        sample_ids = list(queryset.values_list("id", flat=True)[:5])
        message = (
            "EA-AUD-023 迁移被阻断: accounts.0013 不能把未知 DingTalk status "
            "静默降级为 disabled。"
            f" count={count}, sample_ids={sample_ids}, "
            f"supported_statuses={_SUPPORTED_DINGTALK_STATUSES}。"
            "请先显式修复目录状态。"
        )
        raise RuntimeError(message)


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("accounts", "0012_app_capability_and_directory_indexes"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.AddField(
            model_name="dingtalkusermirror",
            name="email",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
        migrations.AddField(
            model_name="dingtalkusermirror",
            name="mobile",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="dingtalkusermirror",
            name="employee_number",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="dingtalkusermirror",
            name="is_tombstone",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="dingtalkusermirror",
            name="last_seen_generation",
            field=models.BigIntegerField(default=-1),
        ),
        migrations.AddField(
            model_name="dingtalkusermirror",
            name="departed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(assert_supported_directory_status, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="dingtalkusermirror",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "active"),
                    ("disabled", "disabled"),
                    ("departed", "departed"),
                ],
                default="active",
                max_length=16,
            ),
        ),
    ]
