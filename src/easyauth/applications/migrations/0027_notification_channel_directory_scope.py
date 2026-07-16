from collections.abc import Iterator, Sequence
from typing import ClassVar, Protocol, Self, cast

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.operations.base import Operation


class NotificationChannelScopeMigrationError(RuntimeError):
    pass


class _HistoricalQuery(Protocol):
    def __iter__(self) -> Iterator[object]: ...
    def filter(self, **kwargs: object) -> Self: ...
    def exclude(self, **kwargs: object) -> Self: ...
    def values_list(self, *fields: str, flat: bool = False) -> Self: ...
    def update(self, **kwargs: object) -> int: ...
    def exists(self) -> bool: ...


class _HistoricalModel(Protocol):
    objects: ClassVar[_HistoricalQuery]


def _directory_scopes(apps: Apps) -> list[tuple[str, str]]:
    scopes: set[tuple[str, str]] = set()
    for model_name in (
        "DingTalkDirectorySyncState",
        "DingTalkUserMirror",
        "DingTalkDepartmentMirror",
    ):
        model = cast(
            "type[_HistoricalModel]",
            cast("object", apps.get_model("accounts", model_name)),
        )
        scopes.update(
            cast(
                "list[tuple[str, str]]",
                list(model.objects.values_list("source_slug", "corp_id")),
            ),
        )
    return sorted(scopes)


def scope_notification_channels(
    apps: Apps,
    _schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    channel = cast(
        "type[_HistoricalModel]",
        cast("object", apps.get_model("applications", "AppNotificationChannel")),
    )
    unique_scopes = _directory_scopes(apps)
    if len(unique_scopes) == 1:
        source_slug, corp_id = unique_scopes[0]
        _ = channel.objects.update(
            directory_source_slug=source_slug,
            corp_id=corp_id,
        )
        return
    if channel.objects.exists():
        message = (
            "通知通道目录作用域迁移被阻断: 正式目录快照中的 source/corp 不唯一, "
            "无法安全推断已有通道作用域。"
        )
        raise NotificationChannelScopeMigrationError(message)


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("accounts", "0013_directory_user_contact_tombstones"),
        ("applications", "0026_app_notification_channel"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.AddField(
            model_name="appnotificationchannel",
            name="directory_source_slug",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.AddField(
            model_name="appnotificationchannel",
            name="corp_id",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
        migrations.RunPython(scope_notification_channels, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="appnotificationchannel",
            name="directory_source_slug",
            field=models.CharField(max_length=128),
        ),
        migrations.AlterField(
            model_name="appnotificationchannel",
            name="corp_id",
            field=models.CharField(max_length=128),
        ),
    ]
