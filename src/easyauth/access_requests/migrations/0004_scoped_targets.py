from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import django.db.models.deletion
from django.db import migrations, models

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.apps.registry import Apps
    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
    from django.db.migrations.operations.base import Operation


def migrate_roles_to_groups(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    _ = schema_editor
    AccessRequestGroup = apps.get_model("access_requests", "AccessRequestGroup")
    AccessRequestRole = apps.get_model("access_requests", "AccessRequestRole")
    AuthorizationGroup = apps.get_model("applications", "AuthorizationGroup")

    request_roles = AccessRequestRole.objects.select_related("access_request", "role")
    group_keys = {
        (request_role.role.app_id, request_role.role.key)
        for request_role in request_roles
    }
    groups_by_app_and_key = {
        (group.app_id, group.key): group
        for group in AuthorizationGroup.objects.filter(
            app_id__in={app_id for app_id, _key in group_keys},
            key__in={key for _app_id, key in group_keys},
        )
    }

    missing_groups = sorted(group_keys - set(groups_by_app_and_key))
    if missing_groups:
        missing = ", ".join(f"app_id={app_id}, key={key}" for app_id, key in missing_groups)
        message = f"Missing authorization groups for access request role migration: {missing}"
        raise RuntimeError(message)

    AccessRequestGroup.objects.bulk_create(
        [
            AccessRequestGroup(
                access_request_id=request_role.access_request_id,
                authorization_group_id=groups_by_app_and_key[
                    (request_role.role.app_id, request_role.role.key)
                ].id,
                created_at=request_role.created_at,
            )
            for request_role in request_roles
        ],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("applications", "0009_atomic_authorization_models"),
        ("access_requests", "0003_dingtalk_process_instance"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RemoveConstraint(
            model_name="accessrequestpermission",
            name="access_requests_request_permission_unique",
        ),
        migrations.CreateModel(
            name="AccessRequestGroup",
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
                        related_name="target_groups",
                        to="access_requests.accessrequest",
                    ),
                ),
                (
                    "authorization_group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="access_request_groups",
                        to="applications.authorizationgroup",
                    ),
                ),
            ],
            options={
                "ordering": ["access_request_id", "authorization_group__key"],
            },
        ),
        migrations.AddField(
            model_name="accessrequestpermission",
            name="scope_key",
            field=models.CharField(default="GLOBAL", max_length=128),
        ),
        migrations.AlterModelOptions(
            name="accessrequestpermission",
            options={
                "ordering": ["access_request_id", "permission__key", "scope_key"],
            },
        ),
        migrations.RunPython(migrate_roles_to_groups, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="accessrequestgroup",
            constraint=models.UniqueConstraint(
                fields=("access_request", "authorization_group"),
                name="access_requests_request_group_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="accessrequestpermission",
            constraint=models.UniqueConstraint(
                fields=("access_request", "permission", "scope_key"),
                name="access_requests_request_permission_unique",
            ),
        ),
    ]
