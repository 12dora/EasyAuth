from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol, cast

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.apps.registry import Apps
    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
    from django.db.migrations.operations.base import Operation


class _MigrationQuerySet(Protocol):
    def order_by(self, *field_names: str) -> _MigrationQuerySet: ...

    def count(self) -> int: ...

    def values_list(self, field_name: str, *, flat: bool = False) -> Sequence[int]: ...


class _MigrationManager(Protocol):
    def all(self) -> _MigrationQuerySet: ...


class _HistoricalAccessGrant(Protocol):
    objects: _MigrationManager


def assert_no_parent_lifecycle_grants(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    _ = schema_editor
    access_grant = cast(
        "_HistoricalAccessGrant",
        apps.get_model("grants", "AccessGrant"),
    )
    queryset = access_grant.objects.all().order_by("id")
    count = queryset.count()
    if count:
        sample_ids = list(queryset.values_list("id", flat=True)[:5])
        message = (
            "EA-AUD-023 迁移被阻断: grants.0005 不能把父级 grant_type/grant_expires_at "
            "静默迁移到成员期限或删除已有授权。"
            f" count={count}, sample_ids={sample_ids}。请先导出并按成员级期限契约显式重建授权。"
        )
        raise RuntimeError(message)


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("grants", "0004_delete_access_grant_role"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RunPython(assert_no_parent_lifecycle_grants, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="accessgrant",
            name="grants_access_grant_type_supported",
        ),
        migrations.RemoveConstraint(
            model_name="accessgrant",
            name="grants_access_grant_expiration_shape",
        ),
        migrations.RemoveField(model_name="accessgrant", name="grant_type"),
        migrations.RemoveField(model_name="accessgrant", name="grant_expires_at"),
        migrations.AddField(
            model_name="accessgrantgroup",
            name="expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="accessgrantpermission",
            name="expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
