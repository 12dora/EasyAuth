from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("audit", "0002_audit_log_retention_indexes"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.CreateModel(
            name="DirectoryAuditBucket",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("app_key", models.CharField(max_length=64)),
                ("endpoint", models.CharField(max_length=64)),
                ("hour_bucket", models.CharField(max_length=10)),
                ("call_count", models.PositiveIntegerField(default=0)),
                ("q_present", models.BooleanField(default=False)),
                ("result_count", models.PositiveIntegerField(default=0)),
                ("credential_id", models.CharField(blank=True, max_length=64)),
                ("flushed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["hour_bucket", "app_key", "endpoint"],
            },
        ),
        migrations.AddConstraint(
            model_name="directoryauditbucket",
            constraint=models.UniqueConstraint(
                fields=("app_key", "endpoint", "hour_bucket"),
                name="audit_directory_bucket_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="directoryauditbucket",
            constraint=models.CheckConstraint(
                condition=models.Q(("call_count__gte", 0)),
                name="audit_directory_bucket_call_count_non_negative",
            ),
        ),
        migrations.AddIndex(
            model_name="directoryauditbucket",
            index=models.Index(
                fields=["flushed_at", "hour_bucket", "id"],
                name="audit_dir_bucket_flush_idx",
            ),
        ),
    ]
