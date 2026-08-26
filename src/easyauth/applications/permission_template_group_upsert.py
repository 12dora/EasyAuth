"""写入权限组树: 先清 parent 写标量, 再按深度绑 parent。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.applications.models import PermissionGroup
from easyauth.applications.permission_template_types import PermissionTemplateImportError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from easyauth.applications.models import App
    from easyauth.applications.permission_template_types import (
        AppManifestInput,
        AppManifestPermissionGroupInput,
    )

__all__ = ["_upsert_permission_groups"]


def _upsert_permission_groups(
    app: App,
    manifest: AppManifestInput,
) -> dict[str, PermissionGroup]:
    depth_by_key = _permission_group_depths(manifest.permission_groups)
    incoming_keys = {spec.key for spec in manifest.permission_groups}
    group_by_key = _prepare_permission_group_rows(app, manifest)
    _attach_incoming_group_parents(manifest, group_by_key, depth_by_key)
    _detach_deleted_group_parents(app, incoming_keys)
    return _deactivate_missing_group_rows(app, incoming_keys)


def _prepare_permission_group_rows(
    app: App,
    manifest: AppManifestInput,
) -> dict[str, PermissionGroup]:
    group_by_key = {group.key: group for group in PermissionGroup.objects.filter(app=app)}
    for spec in manifest.permission_groups:
        group = group_by_key.get(spec.key)
        if group is None:
            group = PermissionGroup(app=app, key=spec.key, depth=1)
        group.name = spec.name
        group.name_en = spec.name_en
        group.description = spec.description
        group.description_en = spec.description_en
        group.display_order = spec.display_order
        group.is_active = spec.is_active
        group.parent = None
        group.depth = 1
        group.full_clean(exclude=["parent"])
        group.save()
        group_by_key[spec.key] = group
    return group_by_key


def _attach_incoming_group_parents(
    manifest: AppManifestInput,
    group_by_key: dict[str, PermissionGroup],
    depth_by_key: Mapping[str, int],
) -> None:
    for spec in sorted(manifest.permission_groups, key=lambda group: depth_by_key[group.key]):
        group = group_by_key[spec.key]
        group.parent = group_by_key.get(spec.parent_key) if spec.parent_key else None
        group.depth = depth_by_key[spec.key]
        group.full_clean()
        group.save(update_fields=["parent", "depth", "updated_at"])


def _detach_deleted_group_parents(app: App, incoming_keys: set[str]) -> None:
    _detach_missing_permission_group_roots(app, incoming_keys)
    _sync_permission_group_depths(app)


def _deactivate_missing_group_rows(
    app: App,
    incoming_keys: set[str],
) -> dict[str, PermissionGroup]:
    group_by_key = {group.key: group for group in PermissionGroup.objects.filter(app=app)}
    for key, group in group_by_key.items():
        if key not in incoming_keys and group.is_active:
            group.is_active = False
            group.full_clean()
            group.save(update_fields=["is_active", "updated_at"])
    return group_by_key


def _permission_group_depths(
    groups: tuple[AppManifestPermissionGroupInput, ...],
) -> dict[str, int]:
    group_by_key = {group.key: group for group in groups}
    depths: dict[str, int] = {}

    def depth_for(key: str, stack: tuple[str, ...] = ()) -> int:
        if key in depths:
            return depths[key]
        if key in stack:
            raise PermissionTemplateImportError(
                code="app_manifest_permission_group_cycle",
                message="App manifest permission group 不能形成环。",
                subject=key,
            )
        parent_key = group_by_key[key].parent_key
        depth = 1 if not parent_key else depth_for(parent_key, (*stack, key)) + 1
        depths[key] = depth
        return depth

    for group in groups:
        _ = depth_for(group.key)
    return depths


def _sync_permission_group_depths(app: App) -> None:
    groups = list(PermissionGroup.objects.filter(app=app).select_related("parent"))
    group_by_id = {group.id: group for group in groups}
    depth_by_id: dict[int, int] = {}

    def depth_for(group: PermissionGroup) -> int:
        if group.id in depth_by_id:
            return depth_by_id[group.id]
        parent_id = group.parent_id
        depth = 1 if parent_id is None else depth_for(group_by_id[parent_id]) + 1
        depth_by_id[group.id] = depth
        return depth

    for group in groups:
        _ = depth_for(group)

    for group in sorted(groups, key=lambda item: depth_by_id[item.id]):
        expected_depth = depth_by_id[group.id]
        if group.depth == expected_depth:
            continue
        group.depth = expected_depth
        if group.parent_id is not None:
            group.parent = group_by_id[group.parent_id]
        group.full_clean()
        group.save(update_fields=["depth", "updated_at"])


def _detach_missing_permission_group_roots(app: App, incoming_keys: set[str]) -> None:
    group_by_key = {group.key: group for group in PermissionGroup.objects.filter(app=app)}
    incoming_ids = {group_by_key[key].id for key in incoming_keys}
    for key, group in group_by_key.items():
        if key in incoming_keys or group.parent_id not in incoming_ids:
            continue
        group.parent = None
        group.depth = 1
        group.full_clean()
        group.save(update_fields=["parent", "depth", "updated_at"])
