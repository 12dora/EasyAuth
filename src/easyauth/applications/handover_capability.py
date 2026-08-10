"""App 交接能力从 manifest 同步(01 §5.2)。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

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
    BLOCKED_REASON_CAPABILITY_UNDECLARED,
    TASK_OPEN_STATUSES,
    HandoverAppAction,
    HandoverAssetType,
    HandoverTask,
)
from easyauth.webhooks.models import AppWebhookConfig

if TYPE_CHECKING:
    from easyauth.applications.ops_models import JsonValue

CAPABILITY_HANDOVER_V2: Final = "handover.v2"
CAPABILITY_HANDOVER_NONE: Final = "handover.none"


def sync_handover_capability_from_manifest(
    app: App,
    lifecycle: object,
    *,
    actor_id: str,
) -> None:
    """在既有 manifest push 事务内调用。lifecycle 需提供 capabilities / handover_url / handover_asset_types。"""
    capabilities = list(getattr(lifecycle, "capabilities", ()) or ())
    handover_url = str(getattr(lifecycle, "handover_url", "") or "")
    raw_types = list(getattr(lifecycle, "handover_asset_types", ()) or ())
    has_v2 = CAPABILITY_HANDOVER_V2 in capabilities
    has_none = CAPABILITY_HANDOVER_NONE in capabilities
    previous = app.handover_capability

    if has_v2 and has_none:
        _ = AuditService.record(
            AuditRecord(
                actor_type="system",
                actor_id=actor_id or LIFECYCLE_ACTOR_ID,
                action="handover_capability_conflict",
                target_type="app",
                target_id=app.app_key,
                metadata={"capabilities": capabilities},
            ),
        )
        if previous != HANDOVER_CAPABILITY_NONE:
            app.handover_capability = HANDOVER_CAPABILITY_UNDECLARED
            app.handover_capability_synced_at = timezone.now()
            app.save(
                update_fields=[
                    "handover_capability",
                    "handover_capability_synced_at",
                    "updated_at",
                ],
            )
        return

    if has_v2 and handover_url:
        asset_types = [_normalize_asset_type(item) for item in raw_types]
        app.handover_capability = HANDOVER_CAPABILITY_DECLARED
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
        config, _created = AppWebhookConfig.objects.get_or_create(app=app)
        if config.handover_url != handover_url:
            config.handover_url = handover_url
            config.enabled = True
            config.save(update_fields=["handover_url", "enabled", "updated_at"])
        if previous == HANDOVER_CAPABILITY_UNDECLARED:
            reconcile_blocked_actions(app, actor_id=actor_id)
        return

    if has_none and not raw_types:
        # none 必须由超管声明人或 manifest 路径带 declared_by; 此处仅当已是 none 时刷新时间。
        if previous == HANDOVER_CAPABILITY_NONE:
            app.handover_capability_synced_at = timezone.now()
            app.save(update_fields=["handover_capability_synced_at", "updated_at"])
        elif previous != HANDOVER_CAPABILITY_NONE:
            # manifest 声明 none 但无运营声明人 → undeclared(不静默写 none)。
            app.handover_capability = HANDOVER_CAPABILITY_UNDECLARED
            app.handover_capability_synced_at = timezone.now()
            app.save(
                update_fields=[
                    "handover_capability",
                    "handover_capability_synced_at",
                    "updated_at",
                ],
            )
        return

    # 拉取失败 / 无能力串: 不覆盖已有 none。
    if previous == HANDOVER_CAPABILITY_NONE:
        return
    app.handover_capability = HANDOVER_CAPABILITY_UNDECLARED
    app.handover_capability_synced_at = timezone.now()
    app.save(
        update_fields=[
            "handover_capability",
            "handover_capability_synced_at",
            "updated_at",
        ],
    )


def reconcile_blocked_actions(app: App, *, actor_id: str) -> None:
    """undeclared → declared 后, 同事务 reconcile open task 上的 blocked action。"""
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
                actor_type="system",
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
        return {
            "type": str(item.get("type", "")),
            "label": str(item.get("label", "")),
            "detail_supported": bool(item.get("detail_supported", False)),
            "releasable": bool(item.get("releasable", False)),
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
