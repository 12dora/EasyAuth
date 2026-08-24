"""定义转岗授权差异的键、序列化、期限计算和值对象。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from django.utils import timezone

from easyauth.applications.models import App, AuthorizationGroup, Permission
from easyauth.lifecycle.core import TEMPLATE_TERM_INVALID_MESSAGE
from easyauth.lifecycle.errors import HandoverError

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.applications.ops_models import JsonValue
    from easyauth.lifecycle.models import HandoverGrantItem, OnboardingTemplateRevisionItem


@dataclass(frozen=True, slots=True)
class _FrozenTransferAddItem:
    app: App
    authorization_group: AuthorizationGroup | None
    permission: Permission | None
    scope_key: str
    grant_type: str
    duration_days: int | None


@dataclass(frozen=True, slots=True)
class _TransferDiffKeys:
    revoke: list[str]
    add: list[str]
    keep: list[str]


FrozenTransferAddItem = _FrozenTransferAddItem
TransferDiffKeys = _TransferDiffKeys


def _transfer_diff_keys(
    current_entries: dict[str, HandoverGrantItem],
    template_entries: dict[str, OnboardingTemplateRevisionItem],
) -> _TransferDiffKeys:
    current_keys = set(current_entries)
    template_keys = set(template_entries)
    common = current_keys & template_keys
    term_changes = {
        key
        for key in common
        if template_term_replaces_snapshot(
            template_entries[key],
            current_entries[key],
        )
    }
    return _TransferDiffKeys(
        revoke=sorted(current_keys - template_keys),
        add=sorted((template_keys - current_keys) | term_changes),
        keep=sorted(common - term_changes),
    )


transfer_diff_keys = _transfer_diff_keys


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
