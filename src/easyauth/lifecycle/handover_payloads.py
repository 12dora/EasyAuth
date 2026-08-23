"""交接载荷构造、分片计划与批次进度管理。"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Final, cast

from easyauth.lifecycle.core import (
    HOOK_EVENT_EXECUTE,
    HOOK_EVENT_PREVIEW,
)
from easyauth.lifecycle.errors import HandoverConflictError
from easyauth.lifecycle.handover_shared import (
    task_id,
)
from easyauth.lifecycle.models import (
    ASSET_ACTION_RELEASE,
    ASSET_ACTION_SKIP,
    ASSET_ACTION_TRANSFER,
    BATCH_PLAN_STATUS_ACTIVE,
    BATCH_PLAN_STATUS_DONE,
    HandoverAppAction,
    HandoverAssetType,
    HandoverBatchPlan,
    HandoverExecutionBatch,
)

if TYPE_CHECKING:
    from easyauth.applications.ops_models import JsonValue


_BATCH_PLAN_IN_PROGRESS_MESSAGE: Final = "batch_plan_in_progress"
_BATCH_PLAN_EXHAUSTED_MESSAGE: Final = "batch_plan_exhausted"

# ---------------------------------------------------------------------------
# payload / helpers
# ---------------------------------------------------------------------------


def build_preview_payload(action: HandoverAppAction) -> dict[str, JsonValue]:
    return {
        "task_id": task_id(action),
        "event_type": HOOK_EVENT_PREVIEW,
        "kind": action.task.kind,
        "from_user_id": action.task.subject_user.authentik_user_id,
        "generation": action.generation,
        "mode": "preview",
    }


def build_execute_payload(action: HandoverAppAction) -> dict[str, JsonValue]:
    payload, _is_final, _plan_no = build_execute_payload_for_plan(action, plan=None)
    return payload


def build_execute_payload_for_plan(
    action: HandoverAppAction,
    plan: HandoverBatchPlan | None,
) -> tuple[dict[str, JsonValue], bool, int | None]:
    """契约 §10.5: assignments 用 asset_type / id, 不是 type / asset_id。"""
    if plan is None:
        assignments = _full_assignments(action)
        return (
            _execute_envelope(action, assignments=assignments, batch_id=action.batch_seq + 1),
            True,
            None,
        )
    if plan.assignment_hash != _assignment_hash(action, plan=plan):
        raise HandoverConflictError(_BATCH_PLAN_IN_PROGRESS_MESSAGE)
    next_no = int(plan.completed_batches) + 1
    if next_no > int(plan.total):
        raise HandoverConflictError(_BATCH_PLAN_EXHAUSTED_MESSAGE)
    chunks = plan.chunks if isinstance(plan.chunks, list) else []
    chunk = chunks[next_no - 1] if next_no - 1 < len(chunks) else []
    is_final = next_no >= int(plan.total)
    assignments = _chunk_assignments(action, chunk=chunk, is_final=is_final)
    return (
        _execute_envelope(action, assignments=assignments, batch_id=action.batch_seq + 1),
        is_final,
        next_no,
    )


def _execute_envelope(
    action: HandoverAppAction,
    *,
    assignments: list[dict[str, JsonValue]],
    batch_id: int,
) -> dict[str, JsonValue]:
    return {
        "task_id": task_id(action),
        "event_type": HOOK_EVENT_EXECUTE,
        "kind": action.task.kind,
        "from_user_id": action.task.subject_user.authentik_user_id,
        "generation": action.generation,
        "snapshot_token": action.snapshot_token,
        "mode": "execute",
        "batch_id": batch_id,
        "assignments": assignments,
    }


def _full_assignments(action: HandoverAppAction) -> list[dict[str, JsonValue]]:
    assignments: list[dict[str, JsonValue]] = []
    types = HandoverAssetType.objects.filter(
        action=action,
        generation=action.generation,
    ).prefetch_related("overrides", "default_to_user", "overrides__to_user")
    for asset_type in types:
        overrides: list[dict[str, JsonValue]] = [
            {
                "id": ov.asset_id,
                "action": ov.action,
                "to_user_id": (
                    ov.to_user.authentik_user_id if ov.to_user is not None else None
                ),
            }
            for ov in asset_type.overrides.all()
        ]
        assignments.append(
            {
                "asset_type": asset_type.type_key,
                "default_action": asset_type.default_action,
                "default_to_user_id": (
                    asset_type.default_to_user.authentik_user_id
                    if asset_type.default_to_user is not None
                    else None
                ),
                "overrides": overrides,
            },
        )
    return assignments


def audit_assignment_summary(action: HandoverAppAction) -> list[JsonValue]:
    """审计只保留分配策略与覆盖数量, 不写人员标识或资产 ID。"""
    types = HandoverAssetType.objects.filter(
        action=action,
        generation=action.generation,
    ).prefetch_related("overrides")
    return [
        {
            "asset_type": str(asset_type.type_key)[:64],
            "default_action": asset_type.default_action,
            "override_count": asset_type.overrides.count(),
        }
        for asset_type in types
    ]


def audit_result_summary(summary: dict[str, JsonValue] | None) -> dict[str, JsonValue]:
    if not summary:
        return {}
    safe: dict[str, JsonValue] = {}
    for type_key, value in summary.items():
        if not isinstance(type_key, str) or not isinstance(value, dict):
            continue
        counts: dict[str, JsonValue] = {}
        for field in ("transferred", "released", "skipped", "merged", "failed"):
            count = value.get(field)
            if type(count) is int and count >= 0:
                counts[field] = count
        safe[type_key[:64]] = counts
    return safe


def _chunk_allowed_ids(chunk: object) -> dict[str, set[str]]:
    """把批次描述解析成 asset_type → 本批允许携带的 asset id 集合。"""
    allowed_ids_by_type: dict[str, set[str]] = {}
    if isinstance(chunk, list):
        for entry in chunk:
            if not isinstance(entry, dict):
                continue
            type_key = str(entry.get("asset_type", ""))
            ids = entry.get("ids", [])
            if not type_key:
                continue
            allowed_ids_by_type[type_key] = {str(i) for i in ids if isinstance(i, str | int)}
    return allowed_ids_by_type


def _chunk_type_overrides(
    asset_type: HandoverAssetType,
    *,
    allowed: set[str],
    is_final: bool,
) -> list[dict[str, JsonValue]]:
    overrides: list[dict[str, JsonValue]] = []
    for ov in asset_type.overrides.all():
        if not is_final and ov.asset_id not in allowed:
            continue
        if is_final and ov.action != ASSET_ACTION_SKIP and ov.asset_id not in allowed:
            # 最终批: 本批 remaining transfer/release + 全部 skip。
            # 已在前序批消耗的 transfer/release 不再带。
            continue
        overrides.append(
            {
                "id": ov.asset_id,
                "action": ov.action,
                "to_user_id": (ov.to_user.authentik_user_id if ov.to_user is not None else None),
            },
        )
    return overrides


def _chunk_assignments(
    action: HandoverAppAction,
    *,
    chunk: object,
    is_final: bool,
) -> list[dict[str, JsonValue]]:
    """§2.4.1.1: 非最终批 default_action 强制 skip; 最终批带真实 default + 全部 skip override。"""
    allowed_ids_by_type = _chunk_allowed_ids(chunk)
    result: list[dict[str, JsonValue]] = []
    types = HandoverAssetType.objects.filter(
        action=action,
        generation=action.generation,
    ).prefetch_related("overrides", "default_to_user", "overrides__to_user")
    for asset_type in types:
        type_key = asset_type.type_key
        overrides = _chunk_type_overrides(
            asset_type,
            allowed=allowed_ids_by_type.get(type_key, set()),
            is_final=is_final,
        )
        default_action = asset_type.default_action if is_final else ASSET_ACTION_SKIP
        default_to = (
            asset_type.default_to_user.authentik_user_id
            if is_final and asset_type.default_to_user is not None
            else None
        )
        result.append(
            {
                "asset_type": type_key,
                "default_action": default_action,
                "default_to_user_id": default_to,
                "overrides": overrides,
            },
        )
    return result


def active_batch_plan(action: HandoverAppAction) -> HandoverBatchPlan | None:
    return (
        HandoverBatchPlan.objects.filter(
            action_snapshot_id=action.id,
            generation=action.generation,
            status=BATCH_PLAN_STATUS_ACTIVE,
        )
        .order_by("-id")
        .first()
    )


def ensure_batch_plan_on_413(action: HandoverAppAction) -> HandoverBatchPlan:
    """413: 一次性算好分片计划, 下次 execute 按 chunk 发送。"""
    existing = active_batch_plan(action)
    if existing is not None and existing.completed_batches > 0:
        return existing
    if existing is not None and existing.completed_batches == 0:
        existing.status = "abandoned"
        existing.save(update_fields=["status"])
    assignments = _full_assignments(action)
    chunks = _split_assignments_into_chunks(assignments)
    assignment_hash = _assignment_hash(action, assignments=assignments)
    return HandoverBatchPlan.objects.create(
        action=action,
        action_snapshot_id=int(action.id),
        generation=action.generation,
        total=max(len(chunks), 1),
        chunks=chunks,
        assignment_hash=assignment_hash,
        status=BATCH_PLAN_STATUS_ACTIVE,
        completed_batches=0,
    )


def _merge_completed_batch_row(
    completed_by_type: dict[str, dict[str, dict[str, JsonValue]]],
    row: object,
) -> None:
    """把某已完成批次里一个资产类型的非 skip override 记入 completed_by_type。"""
    if not isinstance(row, dict):
        return
    entry = cast("dict[str, JsonValue]", row)
    type_key = entry.get("asset_type")
    overrides = entry.get("overrides", [])
    if not isinstance(type_key, str) or not isinstance(overrides, list):
        return
    saved = completed_by_type.setdefault(type_key, {})
    for override in overrides:
        if not isinstance(override, dict) or override.get("action") == ASSET_ACTION_SKIP:
            continue
        asset_id = override.get("id")
        if isinstance(asset_id, str):
            saved[asset_id] = dict(override)


def _completed_overrides_by_type(
    plan: HandoverBatchPlan,
) -> dict[str, dict[str, dict[str, JsonValue]]]:
    completed_rows = HandoverExecutionBatch.objects.filter(
        plan=plan,
        plan_batch_no__lte=plan.completed_batches,
        data_completed_at__isnull=False,
    ).order_by("plan_batch_no")
    completed_by_type: dict[str, dict[str, dict[str, JsonValue]]] = {}
    for completed_batch in completed_rows:
        batch_assignments = completed_batch.request_payload.get("assignments", [])
        if not isinstance(batch_assignments, list):
            continue
        for row in batch_assignments:
            _merge_completed_batch_row(completed_by_type, row)
    return completed_by_type


def _restore_completed_overrides(
    canonical_assignments: list[dict[str, JsonValue]],
    completed_by_type: dict[str, dict[str, dict[str, JsonValue]]],
) -> list[dict[str, JsonValue]]:
    """把已完成批次固化的 override 覆盖回当前分配, 按 asset id 排序稳定化。"""
    restored: list[dict[str, JsonValue]] = []
    for row in canonical_assignments:
        type_key = row.get("asset_type")
        raw_overrides = row.get("overrides", [])
        current_overrides: list[dict[str, JsonValue]] = []
        if isinstance(raw_overrides, list):
            current_overrides = [
                dict(override) for override in raw_overrides if isinstance(override, dict)
            ]
        completed = completed_by_type.get(str(type_key), {})
        remaining: list[dict[str, JsonValue]] = [
            override for override in current_overrides if override.get("id") not in completed
        ]
        remaining.extend(completed.values())
        normalized = dict(row)
        normalized["overrides"] = cast(
            "JsonValue",
            sorted(
                remaining,
                key=lambda override: str(override.get("id", "")),
            ),
        )
        restored.append(normalized)
    return restored


def _assignment_hash(
    action: HandoverAppAction,
    *,
    assignments: list[dict[str, JsonValue]] | None = None,
    plan: HandoverBatchPlan | None = None,
) -> str:
    """固化剩余数据分配与权限接收人的 canonical 意图(01 §2.4.1.1)。"""
    canonical_assignments = assignments if assignments is not None else _full_assignments(action)
    if plan is not None and plan.completed_batches > 0:
        canonical_assignments = _restore_completed_overrides(
            canonical_assignments,
            _completed_overrides_by_type(plan),
        )
    intent = {
        "assignments": canonical_assignments,
        "grant_receiver_user_id": (
            action.grant_receiver.authentik_user_id if action.grant_receiver is not None else None
        ),
    }
    return hashlib.sha256(
        json.dumps(intent, sort_keys=True, separators=(",", ":")).encode("utf-8"),
    ).hexdigest()


def _split_assignments_into_chunks(
    assignments: list[dict[str, JsonValue]],
) -> list[JsonValue]:
    """按 soft limit 切 override; 无 override 时整包一批。"""
    # 简化: 把所有 transfer/release override 均分到多批, 每批约 soft limit。
    work_items = _assignment_work_items(assignments)
    if not work_items:
        return [[{"asset_type": str(a.get("asset_type", "")), "ids": []} for a in assignments]]
    # 按字节预算切: 粗略每 50 条一组
    group_size = 50
    chunks: list[JsonValue] = []
    for i in range(0, len(work_items), group_size):
        group = work_items[i : i + group_size]
        by_type: dict[str, list[str]] = {}
        for item in group:
            by_type.setdefault(str(item["asset_type"]), []).append(str(item["id"]))
        chunks.append([{"asset_type": k, "ids": v} for k, v in sorted(by_type.items())])
    return chunks


def _assignment_work_items(
    assignments: list[dict[str, JsonValue]],
) -> list[dict[str, JsonValue]]:
    work_items: list[dict[str, JsonValue]] = []
    for asn in assignments:
        type_key = str(asn.get("asset_type", ""))
        for ov in asn.get("overrides", []) or []:
            if not isinstance(ov, dict):
                continue
            if ov.get("action") in {ASSET_ACTION_TRANSFER, ASSET_ACTION_RELEASE}:
                work_items.append({"asset_type": type_key, "id": str(ov.get("id", ""))})
    return work_items


def bump_plan_progress(action: HandoverAppAction) -> None:
    plan = active_batch_plan(action)
    if plan is None:
        return
    plan.completed_batches = min(int(plan.completed_batches) + 1, int(plan.total))
    if plan.completed_batches >= plan.total:
        plan.status = BATCH_PLAN_STATUS_DONE
        plan.save(update_fields=["completed_batches", "status"])
    else:
        plan.save(update_fields=["completed_batches"])


def complete_active_plan(action: HandoverAppAction) -> None:
    plan = active_batch_plan(action)
    if plan is None:
        return
    plan.completed_batches = int(plan.total)
    plan.status = BATCH_PLAN_STATUS_DONE
    plan.save(update_fields=["completed_batches", "status"])
