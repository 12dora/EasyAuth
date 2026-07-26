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


class _HistoricalAccessRequest(Protocol):
    objects: _MigrationManager


def assert_no_pre_idempotency_requests(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    _ = schema_editor
    access_request = cast(
        "_HistoricalAccessRequest",
        apps.get_model("access_requests", "AccessRequest"),
    )
    queryset = access_request.objects.all().order_by("id")
    count = queryset.count()
    if count:
        sample_ids = list(queryset.values_list("id", flat=True)[:5])
        message = (
            "EA-AUD-023 迁移被阻断: access_requests.0009 不能为已有申请静默生成 "
            "idempotency_key 和 payload_digest, 已拒绝删除历史申请。"
            f" count={count}, sample_ids={sample_ids}。请先导出并按新申请幂等契约显式重建。"
        )
        raise RuntimeError(message)


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("access_requests", "0008_delete_access_request_role"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RunPython(assert_no_pre_idempotency_requests, migrations.RunPython.noop),
        migrations.AddField(
            model_name="accessrequest",
            name="idempotency_key",
            field=models.CharField(max_length=128),
        ),
        migrations.AddField(
            model_name="accessrequest",
            name="payload_digest",
            field=models.CharField(editable=False, max_length=64),
        ),
        migrations.RemoveConstraint(
            model_name="accessrequest",
            name="access_requests_status_supported",
        ),
        migrations.AlterField(
            model_name="accessrequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("submitted", "submitted"),
                    ("approved", "approved"),
                    ("rejected", "rejected"),
                    ("grant_applied", "grant_applied"),
                    ("grant_failed", "grant_failed"),
                    ("grant_expired", "grant_expired"),
                ],
                default="submitted",
                max_length=32,
            ),
        ),
        migrations.AddConstraint(
            model_name="accessrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "submitted",
                        "approved",
                        "rejected",
                        "grant_applied",
                        "grant_failed",
                        "grant_expired",
                    ),
                ),
                name="access_requests_status_supported",
            ),
        ),
        migrations.AddConstraint(
            model_name="accessrequest",
            constraint=models.UniqueConstraint(
                fields=("user", "idempotency_key"),
                name="access_requests_user_idempotency_key_unique",
            ),
        ),
    ]
