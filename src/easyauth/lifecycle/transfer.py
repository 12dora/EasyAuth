from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, cast

from django.db import transaction
from django.utils import timezone

from easyauth.applications.models import App, AuthorizationGroup, Permission
from easyauth.grants.inputs import AuthorizationGroupGrantInput, ScopedDirectGrantInput
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission
from easyauth.grants.services import GrantExpirationInput, GrantMutationInput, GrantService
from easyauth.lifecycle.core import (
    CATALOG_TARGET_DELETED_MESSAGE,
    TEMPLATE_TERM_INVALID_MESSAGE,
    TRANSFER_CONFIRMATION_CONFLICT_MESSAGE,
    TRANSFER_PLAN_REVISION_CONFLICT_MESSAGE,
    TRANSFER_PLAN_STALE_MESSAGE,
    TRANSFER_TASK_REQUIRED_MESSAGE,
    TRANSFER_TEMPLATE_REVISION_MISSING_MESSAGE,
    ensure_task_open,
    ensure_transfer_task_open,
    record_task_event,
    refresh_task_status,
)
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.models import (
    HANDOVER_KIND_TRANSFER,
    ITEM_STATUS_DONE,
    ITEM_STATUS_PENDING,
    ITEM_STATUS_SKIPPED,
    HandoverAppAction,
    HandoverGrantItem,
    HandoverTask,
    OnboardingTemplate,
    OnboardingTemplateRevisionItem,
    TransferPlan,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from easyauth.accounts.models import UserMirror
    from easyauth.applications.ops_models import JsonValue

@dataclass(frozen=True, slots=True)
class _FrozenTransferAddItem:
    app: App
    authorization_group: AuthorizationGroup | None
    permission: Permission | None
    scope_key: str
    grant_type: str
    duration_days: int | None

def build_transfer_grant_diff(
    *,
    task: HandoverTask,
    template: OnboardingTemplate,
) -> TransferPlan:
    """转岗权限差异(§7 决策 9): 撤销不在新模板内的授权 + 补齐新模板, 确认时逐条可勾选。"""
    with transaction.atomic():
        task = HandoverTask.objects.select_for_update().get(pk=task.id)
        ensure_transfer_task_open(task)
        plan = TransferPlan.objects.select_for_update().get(task=task)
        if plan.confirmed_at is not None:
            raise HandoverConflictError(TRANSFER_CONFIRMATION_CONFLICT_MESSAGE)
        template = (
            OnboardingTemplate.objects.select_for_update()
            .select_related("current_revision")
            .get(pk=template.id)
        )
        template_revision = template.current_revision
        if template_revision is None:
            raise HandoverConflictError(TRANSFER_TEMPLATE_REVISION_MISSING_MESSAGE)
        current_entries = {
            grant_item_key(item): item for item in HandoverGrantItem.objects.filter(task=task)
        }
        current_keys = set(current_entries)
        template_entries = {
            template_item_key(item): item
            for item in OnboardingTemplateRevisionItem.objects.select_related(
                "app",
                "authorization_group",
                "permission",
            ).filter(revision=template_revision)
        }
        common = current_keys & set(template_entries)
        term_changes = {
            key
            for key in common
            if template_term_replaces_snapshot(
                template_entries[key],
                current_entries[key],
            )
        }
        revoke = sorted(current_keys - set(template_entries))
        add = sorted((set(template_entries) - current_keys) | term_changes)
        keep = sorted(common - term_changes)
        plan.new_template = template
        plan.new_template_revision = template_revision
        plan.grant_diff = {
            "revoke": [grant_diff_entry(current_entries[key]) for key in revoke],
            "add": [template_diff_entry(template_entries[key]) for key in add],
            "keep": [grant_diff_entry(current_entries[key]) for key in keep],
        }
        plan.revision += 1
        plan.save(
            update_fields=[
                "new_template",
                "new_template_revision",
                "grant_diff",
                "revision",
                "updated_at",
            ],
        )
        return plan


def confirm_transfer_grant_diff(
    *,
    task: HandoverTask,
    revoke_keys: list[str],
    add_keys: list[str],
    plan_revision: int,
    actor_id: str,
) -> TransferPlan:
    """按管理员勾选执行转岗权限调整(EasyAuth 内部完成, 无需钩子)。"""
    canonical_revoke = sorted(set(revoke_keys))
    canonical_add = sorted(set(add_keys))
    with transaction.atomic():
        task = (
            HandoverTask.objects.select_for_update().select_related("subject_user").get(pk=task.id)
        )
        if task.kind != HANDOVER_KIND_TRANSFER:
            raise HandoverConflictError(TRANSFER_TASK_REQUIRED_MESSAGE)
        plan = (
            TransferPlan.objects.select_for_update()
            .select_related("new_template", "new_template_revision")
            .get(task=task)
        )
        if plan.revision != plan_revision:
            raise HandoverConflictError(TRANSFER_PLAN_REVISION_CONFLICT_MESSAGE)
        if plan.confirmed_at is not None:
            if (
                plan.confirmed_revoke_keys == canonical_revoke
                and plan.confirmed_add_keys == canonical_add
            ):
                return plan
            raise HandoverConflictError(TRANSFER_CONFIRMATION_CONFLICT_MESSAGE)
        ensure_task_open(task)
        if plan.new_template is None or plan.new_template_revision is None:
            message = "请先选择新岗位模板并生成差异清单; 当前方案缺少绑定模板修订。"
            raise HandoverError(message)
        diff = plan.grant_diff
        add_entries = diff_entries_by_key(diff, "add")
        allowed_revoke = set(diff_entries_by_key(diff, "revoke"))
        allowed_add = set(add_entries)
        unknown = (set(canonical_revoke) - allowed_revoke) | (set(canonical_add) - allowed_add)
        if unknown:
            message = f"差异项不存在: {sorted(unknown)[0]}。"
            raise HandoverError(message)
        revoke_set = set(canonical_revoke)
        add_set = set(canonical_add)
        frozen_add_items = {
            key: frozen_add_item_from_diff_entry(add_entries[key]) for key in add_set
        }
        apps = {key.split(":", 1)[0] for key in revoke_set | add_set}
        lock_and_validate_transfer_grant_versions(task=task, app_keys=apps)
        for app_key in sorted(apps):
            apply_transfer_diff_for_app(
                subject=task.subject_user,
                app_key=app_key,
                revoke_keys={key for key in revoke_set if key.startswith(f"{app_key}:")},
                add_items=[
                    item
                    for key, item in frozen_add_items.items()
                    if key in add_set and key.startswith(f"{app_key}:")
                ],
                actor_id=actor_id,
            )
        plan.confirmed_at = timezone.now()
        plan.confirmed_revoke_keys = canonical_revoke
        plan.confirmed_add_keys = canonical_add
        plan.save(
            update_fields=[
                "confirmed_at",
                "confirmed_revoke_keys",
                "confirmed_add_keys",
                "updated_at",
            ],
        )
        record_task_event(
            task,
            action="handover_grant_diff_confirmed",
            actor_id=actor_id,
            extra={
                "revoked": cast("JsonValue", canonical_revoke),
                "added": cast("JsonValue", canonical_add),
            },
        )
        _ = refresh_task_status(task)
        return plan


def transfer_selected_grants(action: HandoverAppAction) -> int:
    """把该 APP 勾选的授权快照转授给接收人; 未勾选的标 skipped(§7 决策 12)。"""
    items = list(
        HandoverGrantItem.objects.select_related("authorization_group", "permission").filter(
            task=action.task,
            app=action.app,
            status=ITEM_STATUS_PENDING,
        ),
    )
    if not items:
        return 0
    unselected = [item for item in items if not item.selected]
    now = timezone.now()
    expired = [
        item
        for item in items
        if item.selected and item.grant_expires_at is not None and item.grant_expires_at <= now
    ]
    selected = [item for item in items if item.selected and item not in expired]
    if any(
        (item.target_kind_snapshot == "group" and item.authorization_group is None)
        or (item.target_kind_snapshot == "permission" and item.permission is None)
        for item in selected
    ):
        raise HandoverError(CATALOG_TARGET_DELETED_MESSAGE)
    _ = HandoverGrantItem.objects.filter(id__in=[i.id for i in unselected]).update(
        status=ITEM_STATUS_SKIPPED,
    )
    _ = HandoverGrantItem.objects.filter(id__in=[i.id for i in expired]).update(
        status=ITEM_STATUS_SKIPPED,
    )
    receiver = action.execution_to_user
    if receiver is None or not selected:
        _ = HandoverGrantItem.objects.filter(id__in=[i.id for i in selected]).update(
            status=ITEM_STATUS_SKIPPED,
        )
        return 0
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
    _ = merge_into_current_grant(
        user=receiver,
        app=action.app,
        groups=groups,
        direct_grants=direct_grants,
        actor_id=f"handover_task:{action.task_id}",
    )
    _ = HandoverGrantItem.objects.filter(id__in=[i.id for i in selected]).update(
        status=ITEM_STATUS_DONE,
    )
    return len(selected)


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
    if existing is not None and existing.status == "active":
        _ = GrantService.expire_grant(
            GrantExpirationInput(
                user=user,
                app=app,
                actor_type="system",
                actor_id=actor_id,
                reason="生命周期写入前过期化",
            ),
        )
        existing = AccessGrant.objects.filter(user=user, app=app, is_current=True).first()
    merged_groups: dict[int, AuthorizationGroupGrantInput] = {
        item.authorization_group.id: item for item in groups
    }
    merged_direct: dict[tuple[int, str], ScopedDirectGrantInput] = {
        (direct.permission.id, direct.scope_key): direct for direct in direct_grants
    }
    if existing is not None and existing.status == "active":
        for link in AccessGrantGroup.objects.select_related("authorization_group").filter(
            grant=existing,
        ):
            incoming = merged_groups.get(link.authorization_group.id)
            merged_groups[link.authorization_group.id] = AuthorizationGroupGrantInput(
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
            incoming = merged_direct.get(key)
            merged_direct[key] = ScopedDirectGrantInput(
                permission=permission_link.permission,
                scope_key=permission_link.scope_key,
                expires_at=(
                    permission_link.expires_at
                    if incoming is None
                    else later_expiry(permission_link.expires_at, incoming.expires_at)
                ),
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


def apply_transfer_diff_for_app(
    *,
    subject: UserMirror,
    app_key: str,
    revoke_keys: set[str],
    add_items: list[_FrozenTransferAddItem],
    actor_id: str,
) -> None:
    app = App.objects.get(app_key=app_key)
    existing = AccessGrant.objects.filter(user=subject, app=app, is_current=True).first()
    groups: dict[int, AuthorizationGroupGrantInput] = {}
    direct: dict[tuple[int, str], ScopedDirectGrantInput] = {}
    if existing is not None and existing.status == "active":
        _ = GrantService.expire_grant(
            GrantExpirationInput(
                user=subject,
                app=app,
                actor_type="system",
                actor_id=actor_id,
                reason="转岗差异确认前过期化",
            ),
        )
        existing = AccessGrant.objects.filter(user=subject, app=app, is_current=True).first()
    if existing is not None and existing.status == "active":
        collect_kept_targets(
            existing=existing,
            app_key=app_key,
            revoke_keys=revoke_keys,
            groups=groups,
            direct=direct,
        )
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


def grant_item_key(item: HandoverGrantItem) -> str:
    base = f"{item.app_key_snapshot}:{item.target_kind_snapshot}:{item.target_key_snapshot}"
    if item.target_kind_snapshot == "group":
        return base
    return f"{base}:{item.scope_key}"


def template_item_key(item: OnboardingTemplateRevisionItem) -> str:
    if item.authorization_group is not None:
        return f"{item.app.app_key}:group:{item.authorization_group.key}"
    permission = item.permission
    permission_key = permission.key if permission is not None else ""
    return f"{item.app.app_key}:permission:{permission_key}:{item.scope_key}"


def grant_diff_entry(item: HandoverGrantItem) -> dict[str, JsonValue]:
    return {
        "key": grant_item_key(item),
        "app_key": item.app_key_snapshot,
        "kind": item.target_kind_snapshot,
        "target_key": item.target_key_snapshot,
        "name": item.target_name_snapshot,
        "scope_key": item.scope_key,
        "grant_type": item.grant_type,
        "grant_expires_at": item.grant_expires_at.isoformat()
        if item.grant_expires_at is not None
        else None,
        "selected": True,
    }


def template_diff_entry(item: OnboardingTemplateRevisionItem) -> dict[str, JsonValue]:
    if item.authorization_group is not None:
        kind = "group"
        target_key = item.authorization_group.key
        name = item.authorization_group.name
    else:
        permission = item.permission
        kind = "permission"
        target_key = permission.key if permission is not None else ""
        name = permission.name if permission is not None else ""
    return {
        "key": template_item_key(item),
        "app_key": item.app.app_key,
        "kind": kind,
        "target_key": target_key,
        "name": name,
        "scope_key": item.scope_key,
        "grant_type": item.grant_type,
        "duration_days": item.duration_days,
        "selected": True,
    }


def diff_list(diff: dict[str, JsonValue], name: str) -> list[dict[str, JsonValue]]:
    value = diff.get(name)
    if not isinstance(value, list):
        return []
    return [element for element in value if isinstance(element, dict)]


def diff_entries_by_key(
    diff: dict[str, JsonValue],
    name: str,
) -> dict[str, dict[str, JsonValue]]:
    entries: dict[str, dict[str, JsonValue]] = {}
    for entry in diff_list(diff, name):
        key = entry_key(entry)
        if key:
            entries[key] = entry
    return entries


def entry_key(entry: dict[str, JsonValue]) -> str:
    key = entry.get("key")
    return key if isinstance(key, str) else ""


def template_item_expiry(*, grant_type: str, duration_days: int | None) -> datetime | None:
    if grant_type == "permanent":
        return None
    if grant_type != "timed" or duration_days is None:
        raise HandoverError(TEMPLATE_TERM_INVALID_MESSAGE)
    return timezone.now() + timedelta(days=duration_days)


def revision_item_expiry(item: OnboardingTemplateRevisionItem) -> datetime | None:
    return template_item_expiry(grant_type=item.grant_type, duration_days=item.duration_days)


def frozen_add_item_from_diff_entry(
    entry: dict[str, JsonValue],
) -> _FrozenTransferAddItem:
    app_key = required_diff_text(entry, "app_key")
    kind = required_diff_text(entry, "kind")
    target_key = required_diff_text(entry, "target_key")
    scope_key = optional_diff_text(entry, "scope_key")
    grant_type = required_diff_text(entry, "grant_type")
    duration_days = optional_diff_int(entry, "duration_days")
    app = App.objects.get(app_key=app_key)
    if kind == "group":
        group = AuthorizationGroup.objects.get(app=app, key=target_key)
        return _FrozenTransferAddItem(
            app=app,
            authorization_group=group,
            permission=None,
            scope_key="",
            grant_type=grant_type,
            duration_days=duration_days,
        )
    if kind == "permission":
        permission = Permission.objects.get(app=app, key=target_key)
        return _FrozenTransferAddItem(
            app=app,
            authorization_group=None,
            permission=permission,
            scope_key=scope_key,
            grant_type=grant_type,
            duration_days=duration_days,
        )
    message = f"冻结差异项类型无效: {kind}。"
    raise HandoverError(message)


def required_diff_text(entry: dict[str, JsonValue], field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or value == "":
        message = f"冻结差异项缺少字段 {field}。"
        raise HandoverError(message)
    return value


def optional_diff_text(entry: dict[str, JsonValue], field: str) -> str:
    value = entry.get(field)
    if value is None:
        return ""
    if not isinstance(value, str):
        message = f"冻结差异项字段 {field} 无效。"
        raise HandoverError(message)
    return value


def optional_diff_int(entry: dict[str, JsonValue], field: str) -> int | None:
    value = entry.get(field)
    if value is None:
        return None
    if not isinstance(value, int):
        message = f"冻结差异项字段 {field} 无效。"
        raise HandoverError(message)
    return value


def template_term_replaces_snapshot(
    template_item: OnboardingTemplateRevisionItem,
    snapshot_item: HandoverGrantItem,
) -> bool:
    if template_item.grant_type == "permanent":
        return snapshot_item.grant_expires_at is not None
    return True


def later_expiry(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None or right is None:
        return None
    return max(left, right)
