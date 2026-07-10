from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import django.db.models.deletion
from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.apps.registry import Apps
    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
    from django.db.migrations.operations.base import Operation


def copy_request_approvers(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    _ = schema_editor
    access_request_model = apps.get_model("access_requests", "AccessRequest")
    access_request_approver_model = apps.get_model(
        "access_requests",
        "AccessRequestApprover",
    )
    user_mirror_model = apps.get_model("accounts", "UserMirror")
    approver_ids = {
        user_id
        for access_request in access_request_model.objects.all()
        for user_id in access_request.approver_user_ids
        if isinstance(user_id, str) and user_id
    }
    approver_by_user_id = {
        approver.authentik_user_id: approver
        for approver in user_mirror_model.objects.filter(authentik_user_id__in=approver_ids)
    }
    missing = approver_ids - approver_by_user_id.keys()
    if missing:
        message = f"审批人关系迁移缺少 UserMirror: {sorted(missing)}"
        raise RuntimeError(message)
    access_request_approver_model.objects.bulk_create(
        access_request_approver_model(
            access_request=access_request,
            approver=approver_by_user_id[user_id],
        )
        for access_request in access_request_model.objects.all()
        for user_id in dict.fromkeys(access_request.approver_user_ids)
        if isinstance(user_id, str) and user_id
    )


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("access_requests", "0009_access_request_idempotency"),
        ("accounts", "0011_dingtalkdirectorysyncstate_generation"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.CreateModel(
            name="AccessRequestApprover",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "access_request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="approver_assignments",
                        to="access_requests.accessrequest",
                    ),
                ),
                (
                    "approver",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approval_assignments",
                        to="accounts.usermirror",
                    ),
                ),
            ],
            options={
                "ordering": ["access_request_id", "approver__authentik_user_id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("access_request", "approver"),
                        name="access_requests_request_approver_unique",
                    ),
                ],
            },
        ),
        migrations.RunPython(copy_request_approvers, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="accessrequest",
            name="approver_user_ids",
        ),
    ]
