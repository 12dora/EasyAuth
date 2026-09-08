# 为每个已有应用补齐平台内置授权组 super_admin 及其 grant。

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.db import migrations

from easyauth.applications.builtin_authorization_groups import (
    BUILTIN_SUPER_ADMIN_DESCRIPTION,
    BUILTIN_SUPER_ADMIN_DESCRIPTION_EN,
    BUILTIN_SUPER_ADMIN_KIND,
    BUILTIN_SUPER_ADMIN_NAME,
    BUILTIN_SUPER_ADMIN_NAME_EN,
    super_admin_grant_targets,
)
from easyauth.applications.models.constants import BUILTIN_SUPER_ADMIN_GROUP_KEY

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.apps.registry import Apps
    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
    from django.db.migrations.operations.base import Operation


def backfill_builtin_super_admin(apps: Apps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    app_model = apps.get_model("applications", "App")
    scope_model = apps.get_model("applications", "AppScope")
    permission_model = apps.get_model("applications", "Permission")
    group_model = apps.get_model("applications", "AuthorizationGroup")
    grant_model = apps.get_model("applications", "AuthorizationGroupGrant")
    for app in app_model.objects.all().iterator():
        group = _upsert_group(group_model, app_id=app.pk)
        _sync_grants(
            group=group,
            grant_model=grant_model,
            permission_model=permission_model,
            scope_model=scope_model,
            app_id=app.pk,
        )


def _upsert_group(group_model: type[object], *, app_id: int) -> object:
    group = group_model.objects.filter(  # type: ignore[attr-defined]
        app_id=app_id,
        key=BUILTIN_SUPER_ADMIN_GROUP_KEY,
    ).first()
    if group is None:
        group = group_model(  # type: ignore[misc]
            app_id=app_id,
            key=BUILTIN_SUPER_ADMIN_GROUP_KEY,
        )
    group.kind = BUILTIN_SUPER_ADMIN_KIND
    group.name = BUILTIN_SUPER_ADMIN_NAME
    group.name_en = BUILTIN_SUPER_ADMIN_NAME_EN
    group.description = BUILTIN_SUPER_ADMIN_DESCRIPTION
    group.description_en = BUILTIN_SUPER_ADMIN_DESCRIPTION_EN
    group.requestable = False
    group.is_active = True
    group.save()
    return group


def _sync_grants(
    *,
    group: object,
    grant_model: type[object],
    permission_model: type[object],
    scope_model: type[object],
    app_id: int,
) -> None:
    active_scope_keys = set(
        scope_model.objects.filter(app_id=app_id, is_active=True).values_list(  # type: ignore[attr-defined]
            "key",
            flat=True,
        ),
    )
    permission_ids_and_scopes = [
        (permission.id, permission.supported_scopes)
        for permission in permission_model.objects.filter(  # type: ignore[attr-defined]
            app_id=app_id,
            is_active=True,
            deprecated_at__isnull=True,
        )
    ]
    desired = super_admin_grant_targets(
        permission_ids_and_scopes=permission_ids_and_scopes,
        active_scope_keys=active_scope_keys,
    )
    existing = {
        (grant.permission_id, grant.scope_key): grant
        for grant in grant_model.objects.filter(authorization_group_id=group.pk)  # type: ignore[attr-defined]
    }
    for permission_id, scope_key in desired:
        grant = existing.get((permission_id, scope_key))
        if grant is None:
            grant_model.objects.create(  # type: ignore[attr-defined]
                authorization_group_id=group.pk,  # type: ignore[attr-defined]
                permission_id=permission_id,
                scope_key=scope_key,
                is_active=True,
            )
            continue
        if grant.is_active:
            continue
        grant.is_active = True
        grant.save(update_fields=["is_active", "updated_at"])
    for fingerprint, grant in existing.items():
        if fingerprint in desired or not grant.is_active:
            continue
        grant.is_active = False
        grant.save(update_fields=["is_active", "updated_at"])


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("applications", "0033_app_alias"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RunPython(backfill_builtin_super_admin, migrations.RunPython.noop),
    ]
