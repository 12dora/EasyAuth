from __future__ import annotations

# ruff: noqa: E501, TC002, TC003
from collections.abc import Sequence
from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("accounts", "0001_initial"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.CreateModel(
            name="DingTalkDepartmentMirror",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_slug", models.CharField(max_length=128)),
                ("corp_id", models.CharField(max_length=128)),
                ("dept_id", models.CharField(max_length=128)),
                ("parent_id", models.CharField(blank=True, max_length=128)),
                ("name", models.CharField(max_length=128)),
                ("order", models.IntegerField(default=0)),
                ("last_synced_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["source_slug", "corp_id", "dept_id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source_slug", "corp_id", "dept_id"),
                        name="accounts_dingtalk_dept_unique",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DingTalkUserMirror",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_slug", models.CharField(max_length=128)),
                ("corp_id", models.CharField(max_length=128)),
                ("user_id", models.CharField(max_length=128)),
                ("union_id", models.CharField(blank=True, max_length=128)),
                ("name", models.CharField(blank=True, max_length=128)),
                ("department_ids", models.JSONField(default=list)),
                ("manager_userid", models.CharField(blank=True, max_length=128)),
                ("status", models.CharField(blank=True, max_length=32)),
                ("last_synced_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["source_slug", "corp_id", "user_id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source_slug", "corp_id", "user_id"),
                        name="accounts_dingtalk_user_unique",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DingTalkUserOrgContext",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_slug", models.CharField(max_length=128)),
                ("corp_id", models.CharField(max_length=128)),
                ("user_id", models.CharField(max_length=128)),
                ("departments", models.JSONField(default=list)),
                ("manager", models.JSONField(default=dict)),
                ("manager_chain", models.JSONField(default=list)),
                ("stale", models.BooleanField(default=False)),
                ("last_synced_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["source_slug", "corp_id", "user_id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source_slug", "corp_id", "user_id"),
                        name="accounts_dingtalk_org_unique",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DingTalkDirectorySyncState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source_slug", models.CharField(max_length=128)),
                ("corp_id", models.CharField(max_length=128)),
                ("status", models.CharField(blank=True, max_length=32)),
                ("counters", models.JSONField(default=dict)),
                ("finished_at", models.CharField(blank=True, max_length=64)),
                ("error", models.TextField(blank=True)),
                ("last_synced_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["source_slug", "corp_id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("source_slug", "corp_id"),
                        name="accounts_dingtalk_sync_unique",
                    ),
                ],
            },
        ),
    ]
