"""App 交接能力从 manifest 同步(01 §5.2)。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from django.db import transaction
from django.utils import timezone

from easyauth.applications.models import (
    HANDOVER_CAPABILITY_DECLARED,
    HANDOVER_CAPABILITY_NONE,
    HANDOVER_CAPABILITY_UNDECLARED,
    App,
)
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.lifecycle.core import LIFECYCLE_ACTOR_ID, record_task_event, refresh_task_status
from easyauth.lifecycle.models import (
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_PENDING,
    TASK_OPEN_STATUSES,
    HandoverAppAction,
    HandoverAssetType,
    HandoverTask,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from easyauth.applications.ops_models import JsonValue

CAPABILITY_HANDOVER_V2: Final = "handover.v2"
CAPABILITY_HANDOVER_NONE: Final = "handover.none"


@dataclass(frozen=True, slots=True)
class _ManifestHandoverDeclaration:
    capabilities: list[JsonValue]
    handover_url: str
    raw_types: list[object]
    has_v2: bool
    has_none: bool

    @property
    def has_conflict(self) -> bool:
        return self.has_v2 and self.has_none

    @property
    def has_usable_v2(self) -> bool:
        return self.has_v2 and bool(self.handover_url)

    @property
    def has_empty_none(self) -> bool:
        return self.has_none and not self.raw_types


def sync_handover_capability_from_manifest(
    app: App,
    lifecycle: object,
    *,
    actor_id: str,
    actor_type: str = "system",
) -> None:
    """在既有 manifest push 事务内调用。

    lifecycle 需提供 capabilities / handover_url / handover_asset_types。
    """
    declaration = _manifest_handover_declaration(lifecycle)
    previous = app.handover_capability

    if declaration.has_conflict:
        _record_capability_conflict(
            app,
            capabilities=declaration.capabilities,
            actor_id=actor_id,
            actor_type=actor_type,
        )
        _save_manifest_capability(app, HANDOVER_CAPABILITY_UNDECLARED, [])
        return

    if declaration.has_usable_v2:
        _save_manifest_capability(
            app,
            HANDOVER_CAPABILITY_DECLARED,
            [_normalize_asset_type(item) for item in declaration.raw_types],
        )
        if previous == HANDOVER_CAPABILITY_UNDECLARED:
            reconcile_blocked_actions(app, actor_id=actor_id, actor_type=actor_type)
        return

    if declaration.has_empty_none:
        # none 必须由超管声明人或 manifest 路径带 declared_by; 此处仅当已是 none 时刷新时间。
        if previous == HANDOVER_CAPABILITY_NONE:
            _refresh_capability_sync_time(app)
        else:
            # manifest 声明 none 但无运营声明人 → undeclared(不静默写 none)。
            _save_manifest_capability(app, HANDOVER_CAPABILITY_UNDECLARED, [])
        return

    # 无能力串或 webhook URL 不可用: 已成功处理的 manifest 视为撤销, 清空资产类型。
    # lifecycle 为 None 表示拉取/解析失败, 保留上次已知的资产类型。
    if previous == HANDOVER_CAPABILITY_NONE:
        return
    if lifecycle is None:
        _save_undeclared_capability_keeping_asset_types(app)
        return
    _save_manifest_capability(app, HANDOVER_CAPABILITY_UNDECLARED, [])


def _manifest_handover_declaration(lifecycle: object) -> _ManifestHandoverDeclaration:
    capabilities = list(
        cast("Iterable[JsonValue]", getattr(lifecycle, "capabilities", ()) or ()),
    )
    handover_url = str(getattr(lifecycle, "handover_url", "") or "")
    raw_types = list(
        cast("Iterable[object]", getattr(lifecycle, "handover_asset_types", ()) or ()),
    )
    return _ManifestHandoverDeclaration(
        capabilities=capabilities,
        handover_url=handover_url,
        raw_types=raw_types,
        has_v2=CAPABILITY_HANDOVER_V2 in capabilities,
        has_none=CAPABILITY_HANDOVER_NONE in capabilities,
    )


def _record_capability_conflict(
    app: App,
    *,
    capabilities: list[JsonValue],
    actor_id: str,
    actor_type: str,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type=actor_type,
            actor_id=actor_id or LIFECYCLE_ACTOR_ID,
            action="handover_capability_conflict",
            target_type="app",
            target_id=app.app_key,
            metadata={"capabilities": capabilities},
        ),
    )


def _save_manifest_capability(
    app: App,
    capability: str,
    asset_types: list[JsonValue],
) -> None:
    app.handover_capability = capability
    app.handover_asset_types = asset_types
    app.handover_capability_synced_at = timezone.now()
    app.save(
        update_fields=[
            "handover_capability",
            "handover_asset_types",
            "handover_capability_synced_at",
            "updated_at",
        ],
    )


def _refresh_capability_sync_time(app: App) -> None:
    app.handover_capability_synced_at = timezone.now()
    app.save(update_fields=["handover_capability_synced_at", "updated_at"])


def _save_undeclared_capability_keeping_asset_types(app: App) -> None:
    """拉取或解析失败: 标 undeclared, 不覆盖上次已知的资产类型。"""
    app.handover_capability = HANDOVER_CAPABILITY_UNDECLARED
    app.handover_capability_synced_at = timezone.now()
    app.save(
        update_fields=[
            "handover_capability",
            "handover_capability_synced_at",
            "updated_at",
        ],
    )


def reconcile_blocked_actions(
    app: App,
    *,
    actor_id: str,
    actor_type: str = "system",
) -> None:
    """从 undeclared → declared 后, 同事务 reconcile open task 上的 blocked action。"""
    with transaction.atomic():
        actions = list(
            HandoverAppAction.objects.select_for_update()
            .select_related("task")
            .filter(
                app=app,
                status=ACTION_STATUS_BLOCKED,
                task__status__in=TASK_OPEN_STATUSES,
            ),
        )
        touched_tasks: set[int] = set()
        for action in actions:
            action.status = ACTION_STATUS_PENDING
            action.blocked_reason = ""
            action.generation = action.task.generation
            action.save(
                update_fields=[
                    "status",
                    "blocked_reason",
                    "generation",
                    "updated_at",
                ],
            )
            _seed_asset_type_placeholders(action)
            record_task_event(
                action.task,
                action="handover_action_unblocked",
                actor_id=actor_id or LIFECYCLE_ACTOR_ID,
                actor_type=actor_type,
                extra={"app_key": app.app_key},
            )
            touched_tasks.add(int(action.task_id))
        for task_id in touched_tasks:
            task = HandoverTask.objects.get(pk=task_id)
            _ = refresh_task_status(task)


def declare_handover_none(app: App, *, actor_id: str, reason: str) -> App:
    if not reason.strip():
        message = "声明无用户级数据必须填写理由。"
        raise ValueError(message)
    app.handover_capability = HANDOVER_CAPABILITY_NONE
    app.handover_capability_declared_by = actor_id
    app.handover_capability_declared_at = timezone.now()
    app.handover_asset_types = []
    app.save(
        update_fields=[
            "handover_capability",
            "handover_capability_declared_by",
            "handover_capability_declared_at",
            "handover_asset_types",
            "updated_at",
        ],
    )
    return app


def _normalize_asset_type(item: object) -> dict[str, JsonValue]:
    if isinstance(item, dict):
        values = cast("dict[str, object]", item)
        return {
            "type": str(values.get("type", "")),
            "label": str(values.get("label", "")),
            "detail_supported": bool(values.get("detail_supported", False)),
            "releasable": bool(values.get("releasable", False)),
        }
    type_key = str(getattr(item, "type", "") or getattr(item, "type_key", ""))
    return {
        "type": type_key,
        "label": str(getattr(item, "label", "")),
        "detail_supported": bool(getattr(item, "detail_supported", False)),
        "releasable": bool(getattr(item, "releasable", False)),
    }


def _seed_asset_type_placeholders(action: HandoverAppAction) -> None:
    for item in action.app.handover_asset_types or []:
        if not isinstance(item, dict):
            continue
        type_key = str(item.get("type", ""))
        if not type_key:
            continue
        _ = HandoverAssetType.objects.get_or_create(
            action=action,
            generation=action.generation,
            type_key=type_key,
            defaults={
                "label_snapshot": str(item.get("label", type_key))[:120],
                "count": 0,
                "detail_supported": bool(item.get("detail_supported", False)),
                "releasable": bool(item.get("releasable", False)),
            },
        )
