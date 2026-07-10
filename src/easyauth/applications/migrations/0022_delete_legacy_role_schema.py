from collections.abc import Sequence
from typing import ClassVar

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("applications", "0021_canonicalize_manifest_content_hash"),
        ("access_requests", "0008_delete_access_request_role"),
        ("grants", "0004_delete_access_grant_role"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RemoveConstraint(
            model_name="approvalrule",
            name="applications_approval_rule_one_target",
        ),
        migrations.RemoveField(
            model_name="approvalrule",
            name="role",
        ),
        migrations.AddConstraint(
            model_name="approvalrule",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        authorization_group__isnull=False,
                        permission__isnull=True,
                    )
                    | models.Q(
                        authorization_group__isnull=True,
                        permission__isnull=False,
                    )
                ),
                name="applications_approval_rule_one_target",
            ),
        ),
        migrations.DeleteModel(name="RolePermission"),
        migrations.DeleteModel(name="RoleAccessPolicy"),
        migrations.DeleteModel(name="Role"),
    ]
