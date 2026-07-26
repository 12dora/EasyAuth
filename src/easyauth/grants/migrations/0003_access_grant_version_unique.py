from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol, cast

from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
    from django.db.migrations.operations.base import Operation
    from django.db.migrations.state import StateApps


class _GrantRow(Protocol):
    id: int
    user_id: int
    app_id: int
    version: int


class _MigrationQuerySet(Protocol):
    def __iter__(self) -> Iterator[_GrantRow]: ...


class _MigrationManager(Protocol):
    def order_by(self, *field_names: str) -> _MigrationQuerySet: ...


class _HistoricalAccessGrant(Protocol):
    objects: _MigrationManager


def assert_unique_grant_versions(
    apps: StateApps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    _ = schema_editor
    access_grant = cast("_HistoricalAccessGrant", apps.get_model("grants", "AccessGrant"))
    seen: set[tuple[int, int, int]] = set()
    duplicate_ids: list[int] = []
    for grant in access_grant.objects.order_by("user_id", "app_id", "version", "id"):
        key = (grant.user_id, grant.app_id, grant.version)
        if key in seen:
            duplicate_ids.append(grant.id)
        seen.add(key)
    if duplicate_ids:
        message = (
            "EA-AUD-023 迁移被阻断: grants.0003 不能自动重编号 AccessGrant.version。"
            f" count={len(duplicate_ids)}, sample_ids={duplicate_ids[:5]}。"
            "请先显式修复重复 (user, app, version) 授权事实。"
        )
        raise RuntimeError(message)


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("grants", "0002_scoped_grants"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RunPython(assert_unique_grant_versions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="accessgrant",
            constraint=models.UniqueConstraint(
                fields=("user", "app", "version"),
                name="grants_access_grant_version_unique",
            ),
        ),
    ]
