from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from typing import ClassVar

import django.db.models.deletion
from django.db import migrations, models
from django.db.migrations.operations.base import Operation


def _populate_instance_contract(apps: object, _schema_editor: object) -> None:
    approval_instance = apps.get_model("workflows", "ApprovalInstance")
    for instance in approval_instance.objects.select_related("originator_user").iterator():
        canonical = json.dumps(
            {
                "originator_user_id": instance.originator_user.authentik_user_id,
                "form": instance.form_values,
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        instance.payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        instance.submission_state = (
            "submitted" if instance.dingtalk_process_instance_id else "failed"
        )
        instance.save(update_fields=["payload_hash", "submission_state"])


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [("workflows", "0001_initial")]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.AddField(
            model_name="approvalinstance",
            name="payload_hash",
            field=models.CharField(default="", max_length=64),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="approvalinstance",
            name="provider_correlation_key",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AddField(
            model_name="approvalinstance",
            name="submission_state",
            field=models.CharField(
                choices=[
                    ("pending", "pending"),
                    ("submitting", "submitting"),
                    ("submitted", "submitted"),
                    ("ambiguous", "ambiguous"),
                    ("failed", "failed"),
                ],
                default="pending",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="approvalinstance",
            name="submission_deadline_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(_populate_instance_contract, migrations.RunPython.noop),
        migrations.CreateModel(
            name="PendingApprovalCallback",
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
                ("process_instance_id", models.CharField(max_length=128, unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("approved", "approved"),
                            ("rejected", "rejected"),
                            ("canceled", "canceled"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("pending", "pending"),
                            ("applied", "applied"),
                            ("conflict", "conflict"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("last_error", models.TextField(blank=True)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("applied_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "instance",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="callback_events",
                        to="workflows.approvalinstance",
                    ),
                ),
            ],
            options={"ordering": ["received_at"]},
        ),
        migrations.AddConstraint(
            model_name="approvalinstance",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    submission_state__in=(
                        "pending",
                        "submitting",
                        "submitted",
                        "ambiguous",
                        "failed",
                    ),
                ),
                name="workflows_submission_state_supported",
            ),
        ),
        migrations.AddConstraint(
            model_name="approvalinstance",
            constraint=models.UniqueConstraint(
                condition=~models.Q(dingtalk_process_instance_id=""),
                fields=("dingtalk_process_instance_id",),
                name="workflows_process_instance_id_unique_nonempty",
            ),
        ),
    ]
