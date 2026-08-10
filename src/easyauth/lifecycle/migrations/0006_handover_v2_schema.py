# 数据交接 v2 schema(01 §2.1–§2.5.1): 改名/删列/建表/约束触发器一次完成。

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.apps.registry import Apps
    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
    from django.db.migrations.operations.base import Operation


def install_cross_table_triggers(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    _ = apps
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION lifecycle_check_grant_receiver_offboard()
            RETURNS trigger AS $$
            DECLARE
                task_kind text;
            BEGIN
                SELECT kind INTO task_kind FROM lifecycle_handovertask WHERE id = NEW.task_id;
                IF task_kind IS DISTINCT FROM 'offboard' AND NEW.grant_receiver_id IS NOT NULL THEN
                    RAISE EXCEPTION
                        'lifecycle_grant_receiver_only_offboard: grant_receiver allowed only when task.kind=offboard';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """,
        )
        cursor.execute(
            "DROP TRIGGER IF EXISTS lifecycle_grant_receiver_offboard_trg ON lifecycle_handoverappaction;",
        )
        cursor.execute(
            """
            CREATE CONSTRAINT TRIGGER lifecycle_grant_receiver_offboard_trg
            AFTER INSERT OR UPDATE OF grant_receiver_id, task_id ON lifecycle_handoverappaction
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION lifecycle_check_grant_receiver_offboard();
            """,
        )
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION lifecycle_check_override_releasable()
            RETURNS trigger AS $$
            DECLARE
                parent_releasable boolean;
            BEGIN
                IF NEW.action = 'release' THEN
                    SELECT releasable INTO parent_releasable
                    FROM lifecycle_handoverassettype WHERE id = NEW.asset_type_id;
                    IF parent_releasable IS NOT TRUE THEN
                        RAISE EXCEPTION
                            'lifecycle_override_release_requires_releasable: parent asset type is not releasable';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """,
        )
        cursor.execute(
            "DROP TRIGGER IF EXISTS lifecycle_override_releasable_trg ON lifecycle_handoverassetoverride;",
        )
        cursor.execute(
            """
            CREATE CONSTRAINT TRIGGER lifecycle_override_releasable_trg
            AFTER INSERT OR UPDATE OF action, asset_type_id ON lifecycle_handoverassetoverride
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION lifecycle_check_override_releasable();
            """,
        )


def drop_cross_table_triggers(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    _ = apps
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "DROP TRIGGER IF EXISTS lifecycle_grant_receiver_offboard_trg ON lifecycle_handoverappaction;",
        )
        cursor.execute("DROP FUNCTION IF EXISTS lifecycle_check_grant_receiver_offboard();")
        cursor.execute(
            "DROP TRIGGER IF EXISTS lifecycle_override_releasable_trg ON lifecycle_handoverassetoverride;",
        )
        cursor.execute("DROP FUNCTION IF EXISTS lifecycle_check_override_releasable();")


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("accounts", "0016_retention_indexes"),
        ("applications", "0031_app_handover_capability"),
        ("lifecycle", "0005_handoverappaction_preview_generation"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        # --- HandoverTask: 约束与字段 ---
        migrations.RemoveConstraint(
            model_name="handovertask",
            name="lifecycle_task_kind_supported",
        ),
        migrations.RemoveConstraint(
            model_name="handovertask",
            name="lifecycle_task_one_open_per_subject",
        ),
        migrations.AddField(
            model_name="handovertask",
            name="assignee",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="handover_assignments",
                to="accounts.usermirror",
            ),
        ),
        migrations.AddField(
            model_name="handovertask",
            name="assignee_state",
            field=models.CharField(
                choices=[
                    ("manager", "manager"),
                    ("subject", "subject"),
                    ("superuser_pool", "superuser_pool"),
                ],
                default="superuser_pool",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="handovertask",
            name="escalation_level",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="handovertask",
            name="generation",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="handovertask",
            name="escalation_deadline",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="handovertask",
            name="last_reminded_on",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="handovertask",
            name="creation_idempotency_key",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="handovertask",
            name="creation_payload_sha256",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="handovertask",
            name="escalation_deferred_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="handovertask",
            name="kind",
            field=models.CharField(
                choices=[
                    ("offboard", "offboard"),
                    ("transfer", "transfer"),
                    ("pre_offboard", "pre_offboard"),
                    ("reassign", "reassign"),
                ],
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="handovertask",
            constraint=models.CheckConstraint(
                condition=Q(
                    kind__in=("offboard", "transfer", "pre_offboard", "reassign"),
                ),
                name="lifecycle_task_kind_supported",
            ),
        ),
        migrations.AddConstraint(
            model_name="handovertask",
            constraint=models.CheckConstraint(
                condition=Q(
                    assignee_state__in=("manager", "subject", "superuser_pool"),
                ),
                name="lifecycle_task_assignee_state_supported",
            ),
        ),
        migrations.AddConstraint(
            model_name="handovertask",
            constraint=models.CheckConstraint(
                condition=(
                    Q(assignee_state="superuser_pool", assignee__isnull=True)
                    | (~Q(assignee_state="superuser_pool") & Q(assignee__isnull=False))
                ),
                name="lifecycle_task_assignee_shape",
            ),
        ),
        migrations.AddConstraint(
            model_name="handovertask",
            constraint=models.UniqueConstraint(
                condition=Q(status__in=("pending", "in_progress"))
                & Q(kind__in=("offboard", "transfer", "pre_offboard")),
                fields=["subject_user"],
                name="lifecycle_task_one_open_lifecycle_per_subject",
            ),
        ),
        migrations.AddConstraint(
            model_name="handovertask",
            constraint=models.UniqueConstraint(
                condition=~Q(creation_idempotency_key=""),
                fields=["created_by", "creation_idempotency_key"],
                name="lifecycle_task_creation_idempotency_unique",
            ),
        ),
        # --- HandoverAppAction: 枚举扩容 + 改名/删列/加列 ---
        migrations.RemoveConstraint(
            model_name="handoverappaction",
            name="lifecycle_action_status_supported",
        ),
        migrations.RenameField(
            model_name="handoverappaction",
            old_name="to_user",
            new_name="grant_receiver",
        ),
        migrations.AlterField(
            model_name="handoverappaction",
            name="grant_receiver",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="handover_grant_receiving",
                to="accounts.usermirror",
            ),
        ),
        migrations.RemoveField(model_name="handoverappaction", name="execution_to_user"),
        migrations.RemoveField(model_name="handoverappaction", name="policy"),
        migrations.RemoveField(model_name="handoverappaction", name="execution_policy"),
        migrations.RemoveField(model_name="handoverappaction", name="preview_payload"),
        migrations.RemoveField(model_name="handoverappaction", name="result_payload"),
        migrations.AddField(
            model_name="handoverappaction",
            name="generation",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="handoverappaction",
            name="snapshot_token",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="handoverappaction",
            name="confirm_version",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="handoverappaction",
            name="overrides_version",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="handoverappaction",
            name="batch_seq",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="handoverappaction",
            name="data_completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="handoverappaction",
            name="blocked_reason",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="handoverappaction",
            name="skip_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="handoverappaction",
            name="skipped_by",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name="handoverappaction",
            name="skipped_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="handoverappaction",
            name="approval_instance_warning",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="handoverappaction",
            name="last_error_raw",
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name="handoverappaction",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "pending"),
                    ("previewed", "previewed"),
                    ("executing", "executing"),
                    ("async_pending", "async_pending"),
                    ("async_attention_required", "async_attention_required"),
                    ("done", "done"),
                    ("failed", "failed"),
                    ("skipped", "skipped"),
                    ("blocked", "blocked"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="handoverappaction",
            constraint=models.CheckConstraint(
                condition=Q(
                    status__in=(
                        "pending",
                        "previewed",
                        "executing",
                        "async_pending",
                        "async_attention_required",
                        "done",
                        "failed",
                        "skipped",
                        "blocked",
                    ),
                ),
                name="lifecycle_action_status_supported",
            ),
        ),
        # --- HandoverGrantItem.generation + 唯一约束 ---
        migrations.AddField(
            model_name="handovergrantitem",
            name="generation",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddConstraint(
            model_name="handovergrantitem",
            constraint=models.UniqueConstraint(
                fields=[
                    "task",
                    "generation",
                    "source_grant_id",
                    "target_kind_snapshot",
                    "target_key_snapshot",
                    "scope_key",
                ],
                name="lifecycle_grant_item_unique_per_generation",
            ),
        ),
        # --- 新表 ---
        migrations.CreateModel(
            name="HandoverActionSkipRecord",
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
                ("task_id_snapshot", models.PositiveIntegerField()),
                ("action_snapshot_id", models.PositiveIntegerField()),
                ("generation", models.PositiveIntegerField()),
                ("app_key", models.CharField(max_length=64)),
                ("actor_id", models.CharField(max_length=128)),
                ("reason", models.TextField()),
                ("skipped_at", models.DateTimeField(auto_now_add=True)),
                (
                    "task",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="skip_records",
                        to="lifecycle.handovertask",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["task_id_snapshot"],
                        name="lifecycle_skip_task_snap_idx",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="HandoverAssetType",
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
                ("generation", models.PositiveIntegerField()),
                ("type_key", models.CharField(max_length=64)),
                ("label_snapshot", models.CharField(max_length=120)),
                ("count", models.PositiveIntegerField(default=0)),
                ("detail_supported", models.BooleanField(default=False)),
                ("releasable", models.BooleanField(default=False)),
                (
                    "default_action",
                    models.CharField(
                        choices=[
                            ("transfer", "transfer"),
                            ("release", "release"),
                            ("skip", "skip"),
                        ],
                        default="skip",
                        max_length=8,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "action",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="asset_types",
                        to="lifecycle.handoverappaction",
                    ),
                ),
                (
                    "default_to_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="handover_default_receiving_types",
                        to="accounts.usermirror",
                    ),
                ),
            ],
            options={
                "ordering": ["action_id", "generation", "type_key"],
            },
        ),
        migrations.AddConstraint(
            model_name="handoverassettype",
            constraint=models.UniqueConstraint(
                fields=["action", "generation", "type_key"],
                name="lifecycle_asset_type_unique_per_generation",
            ),
        ),
        migrations.AddConstraint(
            model_name="handoverassettype",
            constraint=models.CheckConstraint(
                condition=Q(default_action__in=("transfer", "release", "skip")),
                name="lifecycle_asset_type_action_supported",
            ),
        ),
        migrations.AddConstraint(
            model_name="handoverassettype",
            constraint=models.CheckConstraint(
                condition=(
                    Q(default_action="transfer", default_to_user__isnull=False)
                    | (~Q(default_action="transfer") & Q(default_to_user__isnull=True))
                ),
                name="lifecycle_asset_type_action_shape",
            ),
        ),
        migrations.AddConstraint(
            model_name="handoverassettype",
            constraint=models.CheckConstraint(
                condition=(
                    ~Q(default_action="release")
                    | Q(default_action="release", releasable=True)
                ),
                name="lifecycle_asset_type_release_requires_releasable",
            ),
        ),
        migrations.CreateModel(
            name="HandoverAssetOverride",
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
                ("asset_id", models.CharField(max_length=128)),
                ("label_snapshot", models.CharField(blank=True, max_length=120)),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("transfer", "transfer"),
                            ("release", "release"),
                            ("skip", "skip"),
                        ],
                        max_length=8,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "asset_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="overrides",
                        to="lifecycle.handoverassettype",
                    ),
                ),
                (
                    "to_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="handover_override_receiving",
                        to="accounts.usermirror",
                    ),
                ),
            ],
            options={
                "ordering": ["asset_type_id", "asset_id"],
            },
        ),
        migrations.AddConstraint(
            model_name="handoverassetoverride",
            constraint=models.UniqueConstraint(
                fields=["asset_type", "asset_id"],
                name="lifecycle_asset_override_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="handoverassetoverride",
            constraint=models.CheckConstraint(
                condition=Q(action__in=("transfer", "release", "skip")),
                name="lifecycle_asset_override_action_supported",
            ),
        ),
        migrations.AddConstraint(
            model_name="handoverassetoverride",
            constraint=models.CheckConstraint(
                condition=(
                    Q(action="transfer", to_user__isnull=False)
                    | (~Q(action="transfer") & Q(to_user__isnull=True))
                ),
                name="lifecycle_asset_override_action_shape",
            ),
        ),
        migrations.CreateModel(
            name="HandoverBatchPlan",
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
                ("action_snapshot_id", models.PositiveIntegerField()),
                ("generation", models.PositiveIntegerField()),
                ("total", models.PositiveIntegerField()),
                ("chunks", models.JSONField()),
                ("assignment_hash", models.CharField(max_length=64)),
                ("status", models.CharField(max_length=16)),
                ("completed_batches", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "action",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="batch_plans",
                        to="lifecycle.handoverappaction",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="handoverbatchplan",
            constraint=models.UniqueConstraint(
                condition=Q(status="active"),
                fields=["action_snapshot_id", "generation"],
                name="lifecycle_batch_plan_one_active",
            ),
        ),
        migrations.AddConstraint(
            model_name="handoverbatchplan",
            constraint=models.CheckConstraint(
                condition=Q(status__in=("active", "abandoned", "done")),
                name="lifecycle_batch_plan_status_supported",
            ),
        ),
        migrations.CreateModel(
            name="HandoverExecutionBatch",
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
                ("action_snapshot_id", models.PositiveIntegerField()),
                ("generation", models.PositiveIntegerField()),
                ("batch_seq", models.PositiveIntegerField()),
                ("is_final", models.BooleanField(default=True)),
                ("snapshot_token", models.CharField(max_length=128)),
                ("request_payload", models.JSONField()),
                ("request_hash", models.CharField(max_length=64)),
                ("status", models.CharField(max_length=16)),
                ("data_completed_at", models.DateTimeField(blank=True, null=True)),
                ("task_snapshot", models.JSONField(default=dict)),
                ("plan_batch_no", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "action",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="execution_batches",
                        to="lifecycle.handoverappaction",
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="batches",
                        to="lifecycle.handoverbatchplan",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="handoverexecutionbatch",
            constraint=models.UniqueConstraint(
                fields=["action_snapshot_id", "generation", "batch_seq"],
                name="lifecycle_execution_batch_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="handoverexecutionbatch",
            constraint=models.CheckConstraint(
                condition=Q(
                    status__in=(
                        "pending",
                        "executing",
                        "async_pending",
                        "data_completed",
                        "done",
                        "failed",
                    ),
                ),
                name="lifecycle_execution_batch_status_supported",
            ),
        ),
        migrations.CreateModel(
            name="HandoverDeliveryAttempt",
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
                ("delivery_seq", models.PositiveIntegerField()),
                ("lease_fence", models.PositiveBigIntegerField()),
                ("outcome", models.CharField(max_length=16)),
                ("http_status", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("response_payload", models.JSONField(blank=True, default=dict)),
                ("error_text", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "batch",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="deliveries",
                        to="lifecycle.handoverexecutionbatch",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="handoverdeliveryattempt",
            constraint=models.UniqueConstraint(
                fields=["batch", "delivery_seq"],
                name="lifecycle_delivery_attempt_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="handoverdeliveryattempt",
            constraint=models.CheckConstraint(
                condition=Q(
                    outcome__in=(
                        "sent",
                        "succeeded",
                        "failed",
                        "async_accepted",
                        "superseded",
                    ),
                ),
                name="lifecycle_delivery_outcome_supported",
            ),
        ),
        migrations.AddConstraint(
            model_name="handoverdeliveryattempt",
            constraint=models.CheckConstraint(
                condition=(
                    Q(outcome__in=("sent", "superseded"))
                    | Q(http_status__isnull=False)
                    | ~Q(error_text="")
                ),
                name="lifecycle_delivery_terminal_evidence",
            ),
        ),
        migrations.CreateModel(
            name="HandoverExecutionLease",
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
                ("generation", models.PositiveIntegerField()),
                ("batch_seq", models.PositiveIntegerField()),
                ("owner", models.CharField(max_length=128)),
                ("fence", models.PositiveBigIntegerField()),
                ("acquired_at", models.DateTimeField(auto_now_add=True)),
                ("lease_expires_at", models.DateTimeField()),
                ("renewed_at", models.DateTimeField(blank=True, null=True)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
                (
                    "action",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="leases",
                        to="lifecycle.handoverappaction",
                    ),
                ),
                (
                    "app",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="handover_leases",
                        to="applications.app",
                    ),
                ),
                (
                    "subject_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="handover_leases",
                        to="accounts.usermirror",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="handoverexecutionlease",
            constraint=models.UniqueConstraint(
                condition=Q(released_at__isnull=True),
                fields=["subject_user", "app"],
                name="lifecycle_lease_one_active_per_subject_app",
            ),
        ),
        migrations.CreateModel(
            name="HandoverLeaseFence",
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
                ("next_fence", models.PositiveBigIntegerField(default=1)),
                (
                    "app",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="applications.app",
                    ),
                ),
                (
                    "subject_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="accounts.usermirror",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="handoverleasefence",
            constraint=models.UniqueConstraint(
                fields=["subject_user", "app"],
                name="lifecycle_fence_unique",
            ),
        ),
        # 跨表不变量: PostgreSQL 约束触发器; SQLite 单测只验 domain。
        migrations.RunPython(install_cross_table_triggers, drop_cross_table_triggers),
    ]
