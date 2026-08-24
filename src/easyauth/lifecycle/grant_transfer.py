"""执行转岗授权快照迁移、现有授权合并及差异落库。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from django.utils import timezone

from easyauth.applications.models import App
from easyauth.grants.inputs import AuthorizationGroupGrantInput, ScopedDirectGrantInput
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission
from easyauth.grants.services import GrantExpirationInput, GrantMutationInput, GrantService
from easyauth.lifecycle.core import CATALOG_TARGET_DELETED_MESSAGE, TRANSFER_PLAN_STALE_MESSAGE
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.models import (
    ITEM_STATUS_DONE,
    ITEM_STATUS_PENDING,
    ITEM_STATUS_SKIPPED,
    HandoverAppAction,
    HandoverGrantItem,
    HandoverTask,
)
from easyauth.lifecycle.transfer_diff import (
    FrozenTransferAddItem,
    later_expiry,
    template_item_expiry,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from easyauth.accounts.models import UserMirror


def transfer_selected_grants(action: HandoverAppAction) -> int:
    """把该 APP 勾选的授权快照转授给接收人; 未勾选的标 skipped(§7 决策 12)。

    同一事务内锁 action 与 grant items, 变更 grant 与 item 状态一起提交。
    """
    items = list(
        HandoverGrantItem.objects.select_for_update(of=("self",))
        .select_related("authorization_group", "permission")
        .filter(
            task=action.task,
            app=action.app,
            generation=action.generation,
            status=ITEM_STATUS_PENDING,
        ),
    )
    if not items:
        return 0
    partition = _partition_pending_grant_items(items, now=timezone.now())
    _assert_transfer_targets_exist(partition.selected)
    _mark_grant_items(partition.unselected, status=ITEM_STATUS_SKIPPED)
    _mark_grant_items(partition.expired, status=ITEM_STATUS_SKIPPED)
    receiver = action.grant_receiver
    if receiver is None or not partition.selected:
        _mark_grant_items(partition.selected, status=ITEM_STATUS_SKIPPED)
        return 0
    groups, direct_grants = _transfer_grant_inputs(partition.selected)
    _ = merge_into_current_grant(
        user=receiver,
        app=action.app,
        groups=groups,
        direct_grants=direct_grants,
        actor_id=f"handover_task:{action.task_id}",
    )
    _mark_grant_items(partition.selected, status=ITEM_STATUS_DONE)
    return len(partition.selected)


@dataclass(frozen=True, slots=True)
class _PendingGrantItems:
    """pending 授权快照按处置去向的三分: 未勾选 / 已过期 / 待转授。"""

    unselected: list[HandoverGrantItem]
    expired: list[HandoverGrantItem]
    selected: list[HandoverGrantItem]


def _partition_pending_grant_items(
    items: list[HandoverGrantItem],
    *,
    now: datetime,
) -> _PendingGrantItems:
    unselected = [item for item in items if not item.selected]
    expired = [
        item
        for item in items
        if item.selected and item.grant_expires_at is not None and item.grant_expires_at <= now
    ]
    selected = [item for item in items if item.selected and item not in expired]
    return _PendingGrantItems(unselected=unselected, expired=expired, selected=selected)


def _assert_transfer_targets_exist(selected: list[HandoverGrantItem]) -> None:
    """勾选项引用的目录对象被删除时快速失败, 不得静默跳过。"""
    if any(
        (item.target_kind_snapshot == "group" and item.authorization_group is None)
        or (item.target_kind_snapshot == "permission" and item.permission is None)
        for item in selected
    ):
        raise HandoverError(CATALOG_TARGET_DELETED_MESSAGE)


def _mark_grant_items(items: list[HandoverGrantItem], *, status: str) -> None:
    _ = HandoverGrantItem.objects.filter(id__in=[i.id for i in items]).update(status=status)


def _transfer_grant_inputs(
    selected: list[HandoverGrantItem],
) -> tuple[list[AuthorizationGroupGrantInput], list[ScopedDirectGrantInput]]:
    groups = [
        AuthorizationGroupGrantInput(
            authorization_group=item.authorization_group,
            expires_at=item.grant_expires_at,
        )
        for item in selected
        if item.authorization_group is not None
    ]
    direct_grants = [
        ScopedDirectGrantInput(
            permission=item.permission,
            scope_key=item.scope_key,
            expires_at=item.grant_expires_at,
        )
        for item in selected
        if item.permission is not None
    ]
    return groups, direct_grants


def merge_into_current_grant(
    *,
    user: UserMirror,
    app: App,
    groups: list[AuthorizationGroupGrantInput],
    direct_grants: list[ScopedDirectGrantInput],
    actor_id: str,
) -> AccessGrant:
    # 接收人已有 current 授权时合并(change), 否则新建; 授权来源经审计 actor_id 可溯源到交接单。
    existing = AccessGrant.objects.filter(user=user, app=app, is_current=True).first()
    existing = _expire_active_grant(
        existing,
        user=user,
        app=app,
        actor_id=actor_id,
        reason="生命周期写入前过期化",
    )
    merged_groups: dict[int, AuthorizationGroupGrantInput] = {
        item.authorization_group.id: item for item in groups
    }
    merged_direct: dict[tuple[int, str], ScopedDirectGrantInput] = {
        (direct.permission.id, direct.scope_key): direct for direct in direct_grants
    }
    if existing is not None and existing.status == "active":
        _merge_existing_grant_targets(
            existing,
            groups=merged_groups,
            direct=merged_direct,
        )
    input_data = GrantMutationInput(
        user=user,
        app=app,
        authorization_groups=tuple(merged_groups.values()),
        direct_grants=tuple(merged_direct.values()),
        actor_type="system",
        actor_id=actor_id,
    )
    if existing is not None:
        return GrantService.change_grant(input_data)
    return GrantService.create_grant(input_data)


def _expire_active_grant(
    existing: AccessGrant | None,
    *,
    user: UserMirror,
    app: App,
    actor_id: str,
    reason: str,
) -> AccessGrant | None:
    if existing is None or existing.status != "active":
        return existing
    _ = GrantService.expire_grant(
        GrantExpirationInput(
            user=user,
            app=app,
            actor_type="system",
            actor_id=actor_id,
            reason=reason,
        ),
    )
    return AccessGrant.objects.filter(user=user, app=app, is_current=True).first()


def _merge_existing_grant_targets(
    existing: AccessGrant,
    *,
    groups: dict[int, AuthorizationGroupGrantInput],
    direct: dict[tuple[int, str], ScopedDirectGrantInput],
) -> None:
    for link in AccessGrantGroup.objects.select_related("authorization_group").filter(
        grant=existing,
    ):
        incoming = groups.get(link.authorization_group.id)
        groups[link.authorization_group.id] = AuthorizationGroupGrantInput(
            authorization_group=link.authorization_group,
            expires_at=(
                link.expires_at
                if incoming is None
                else later_expiry(link.expires_at, incoming.expires_at)
            ),
        )
    for permission_link in AccessGrantPermission.objects.select_related("permission").filter(
        grant=existing,
    ):
        key = (permission_link.permission.id, permission_link.scope_key)
        incoming = direct.get(key)
        direct[key] = ScopedDirectGrantInput(
            permission=permission_link.permission,
            scope_key=permission_link.scope_key,
            expires_at=(
                permission_link.expires_at
                if incoming is None
                else later_expiry(permission_link.expires_at, incoming.expires_at)
            ),
        )


def apply_transfer_diff_for_app(
    *,
    subject: UserMirror,
    app_key: str,
    revoke_keys: set[str],
    add_items: list[FrozenTransferAddItem],
    actor_id: str,
) -> None:
    app = App.objects.get(app_key=app_key)
    existing = AccessGrant.objects.filter(user=subject, app=app, is_current=True).first()
    groups: dict[int, AuthorizationGroupGrantInput] = {}
    direct: dict[tuple[int, str], ScopedDirectGrantInput] = {}
    existing = _expire_active_grant(
        existing,
        user=subject,
        app=app,
        actor_id=actor_id,
        reason="转岗差异确认前过期化",
    )
    if existing is not None and existing.status == "active":
        collect_kept_targets(
            existing=existing,
            app_key=app_key,
            revoke_keys=revoke_keys,
            groups=groups,
            direct=direct,
        )
    _add_transfer_targets(add_items, groups=groups, direct=direct)
    input_data = GrantMutationInput(
        user=subject,
        app=app,
        authorization_groups=tuple(groups.values()),
        direct_grants=tuple(direct.values()),
        actor_type="system",
        actor_id=actor_id,
    )
    if not groups and not direct:
        if existing is not None:
            _ = GrantService.revoke_grant(
                user=subject,
                app=app,
                actor_type="system",
                actor_id=actor_id,
                reason="转岗权限调整",
            )
        return
    if existing is not None:
        _ = GrantService.change_grant(input_data)
    else:
        _ = GrantService.create_grant(input_data)


def _add_transfer_targets(
    add_items: list[FrozenTransferAddItem],
    *,
    groups: dict[int, AuthorizationGroupGrantInput],
    direct: dict[tuple[int, str], ScopedDirectGrantInput],
) -> None:
    for item in add_items:
        item_expiry = template_item_expiry(
            grant_type=item.grant_type,
            duration_days=item.duration_days,
        )
        if item.authorization_group is not None:
            groups[item.authorization_group.id] = AuthorizationGroupGrantInput(
                authorization_group=item.authorization_group,
                expires_at=item_expiry,
            )
        if item.permission is not None:
            direct[(item.permission.id, item.scope_key)] = ScopedDirectGrantInput(
                permission=item.permission,
                scope_key=item.scope_key,
                expires_at=item_expiry,
            )


def lock_and_validate_transfer_grant_versions(
    *,
    task: HandoverTask,
    app_keys: set[str],
) -> None:
    current_by_app = {
        grant.app.app_key: grant
        for grant in AccessGrant.objects.select_for_update()
        .select_related("app")
        .filter(user=task.subject_user, app__app_key__in=app_keys, is_current=True)
    }
    expected_by_app: dict[str, set[int]] = {}
    snapshot_versions = HandoverGrantItem.objects.filter(
        task=task,
        app_key_snapshot__in=app_keys,
    ).values_list("app_key_snapshot", "source_grant_version")
    for app_key, version in cast("Iterable[tuple[str, int]]", snapshot_versions):
        expected_by_app.setdefault(app_key, set()).add(version)
    for app_key, expected_versions in expected_by_app.items():
        current = current_by_app.get(app_key)
        if (
            len(expected_versions) != 1
            or current is None
            or current.version not in expected_versions
        ):
            raise HandoverConflictError(TRANSFER_PLAN_STALE_MESSAGE)


def collect_kept_targets(
    *,
    existing: AccessGrant,
    app_key: str,
    revoke_keys: set[str],
    groups: dict[int, AuthorizationGroupGrantInput],
    direct: dict[tuple[int, str], ScopedDirectGrantInput],
) -> None:
    for link in AccessGrantGroup.objects.select_related("authorization_group").filter(
        grant=existing,
    ):
        key = f"{app_key}:group:{link.authorization_group.key}"
        if key not in revoke_keys:
            groups[link.authorization_group.id] = AuthorizationGroupGrantInput(
                authorization_group=link.authorization_group,
                expires_at=link.expires_at,
            )
    for permission_link in AccessGrantPermission.objects.select_related("permission").filter(
        grant=existing,
    ):
        key = f"{app_key}:permission:{permission_link.permission.key}:{permission_link.scope_key}"
        if key not in revoke_keys:
            direct[(permission_link.permission.id, permission_link.scope_key)] = (
                ScopedDirectGrantInput(
                    permission=permission_link.permission,
                    scope_key=permission_link.scope_key,
                    expires_at=permission_link.expires_at,
                )
            )
