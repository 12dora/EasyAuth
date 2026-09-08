# 为每个已有应用补齐平台内置授权组 super_admin 及其 grant。

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, ClassVar

from django.db import migrations, models, transaction
from django.db.models import F

from easyauth.applications.builtin_authorization_groups import (
    BUILTIN_SUPER_ADMIN_DESCRIPTION,
    BUILTIN_SUPER_ADMIN_DESCRIPTION_EN,
    BUILTIN_SUPER_ADMIN_KIND,
    BUILTIN_SUPER_ADMIN_NAME,
    BUILTIN_SUPER_ADMIN_NAME_EN,
    reserved_authorization_group_collision_message,
    super_admin_grant_targets,
)
from easyauth.applications.models.constants import BUILTIN_SUPER_ADMIN_GROUP_KEY

_SQLITE_TRIGGER_MIGRATIONS: tuple[str, ...] = (
    "easyauth.access_requests.migrations.0014_access_request_relationship_triggers",
    "easyauth.applications.migrations.0029_managed_scope_policy_relationship_triggers",
    "easyauth.grants.migrations.0007_access_grant_relationship_triggers",
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.apps.registry import Apps
    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
    from django.db.migrations.operations.base import Operation


class BuiltinSuperAdminMigrationError(RuntimeError):
    pass


def backfill_builtin_super_admin(apps: Apps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    app_model = apps.get_model("applications", "App")
    scope_model = apps.get_model("applications", "AppScope")
    permission_model = apps.get_model("applications", "Permission")
    group_model = apps.get_model("applications", "AuthorizationGroup")
    grant_model = apps.get_model("applications", "AuthorizationGroupGrant")
    with transaction.atomic():
        for app in app_model.objects.all().iterator():
            group, group_changed = _upsert_group(
                group_model,
                app_id=app.pk,
                app_key=app.app_key,
            )
            grants_changed = _sync_grants(
                group=group,
                grant_model=grant_model,
                permission_model=permission_model,
                scope_model=scope_model,
                app_id=app.pk,
            )
            if group_changed or grants_changed:
                _ = app_model.objects.filter(pk=app.pk).update(
                    catalog_version=F("catalog_version") + 1,
                )


def _upsert_group(
    group_model: type[object],
    *,
    app_id: int,
    app_key: str,
) -> tuple[object, bool]:
    group = group_model.objects.filter(  # type: ignore[attr-defined]
        app_id=app_id,
        key=BUILTIN_SUPER_ADMIN_GROUP_KEY,
    ).first()
    if group is None:
        group = group_model(  # type: ignore[misc]
            app_id=app_id,
            key=BUILTIN_SUPER_ADMIN_GROUP_KEY,
            is_builtin=True,
        )
        _apply_builtin_group_fields(group)
        group.save()  # type: ignore[attr-defined]
        return group, True
    if not group.is_builtin:
        raise BuiltinSuperAdminMigrationError(
            reserved_authorization_group_collision_message(app_key),
        )
    changed = _apply_builtin_group_fields(group)
    if changed:
        group.save()  # type: ignore[attr-defined]
    return group, changed


def _apply_builtin_group_fields(group: object) -> bool:
    assignments: tuple[tuple[str, object], ...] = (
        ("kind", BUILTIN_SUPER_ADMIN_KIND),
        ("name", BUILTIN_SUPER_ADMIN_NAME),
        ("name_en", BUILTIN_SUPER_ADMIN_NAME_EN),
        ("description", BUILTIN_SUPER_ADMIN_DESCRIPTION),
        ("description_en", BUILTIN_SUPER_ADMIN_DESCRIPTION_EN),
        ("requestable", False),
        ("is_active", True),
        ("is_builtin", True),
    )
    changed = False
    for field, value in assignments:
        if getattr(group, field) != value:
            setattr(group, field, value)
            changed = True
    return changed


def _sync_grants(
    *,
    group: object,
    grant_model: type[object],
    permission_model: type[object],
    scope_model: type[object],
    app_id: int,
) -> bool:
    # 只对齐 grant 成员与 is_active; 不改写已有 ManagedScopePolicy 覆盖。
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
    changed = False
    for permission_id, scope_key in desired:
        grant = existing.get((permission_id, scope_key))
        if grant is None:
            grant_model.objects.create(  # type: ignore[attr-defined]
                authorization_group_id=group.pk,  # type: ignore[attr-defined]
                permission_id=permission_id,
                scope_key=scope_key,
                is_active=True,
            )
            changed = True
            continue
        if grant.is_active:
            continue
        grant.is_active = True
        grant.save(update_fields=["is_active", "updated_at"])
        changed = True
    for fingerprint, grant in existing.items():
        if fingerprint in desired or not grant.is_active:
            continue
        grant.is_active = False
        grant.save(update_fields=["is_active", "updated_at"])
        changed = True
    return changed


def drop_sqlite_relationship_triggers(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    if schema_editor.connection.vendor != "sqlite":
        return
    for module_name in _SQLITE_TRIGGER_MIGRATIONS:
        drop_triggers = getattr(importlib.import_module(module_name), "drop_triggers")
        drop_triggers(apps, schema_editor)


def install_sqlite_relationship_triggers(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    if schema_editor.connection.vendor != "sqlite":
        return
    for module_name in _SQLITE_TRIGGER_MIGRATIONS:
        install_triggers = getattr(importlib.import_module(module_name), "install_triggers")
        install_triggers(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies: ClassVar[Sequence[tuple[str, str]]] = [
        ("access_requests", "0014_access_request_relationship_triggers"),
        ("applications", "0033_app_alias"),
        ("grants", "0007_access_grant_relationship_triggers"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RunPython(
            drop_sqlite_relationship_triggers,
            install_sqlite_relationship_triggers,
        ),
        migrations.AddField(
            model_name="authorizationgroup",
            name="is_builtin",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            install_sqlite_relationship_triggers,
            drop_sqlite_relationship_triggers,
        ),
        migrations.RunPython(backfill_builtin_super_admin, migrations.RunPython.noop),
    ]
