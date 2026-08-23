"""资产类型默认分配与 overrides 整体替换(01 §5.4 / §6)。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction

from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.lease import (
    HANDOVER_EXECUTION_IN_FLIGHT,
    assignment_mutation_in_flight,
)
from easyauth.lifecycle.models import (
    ACTION_STATUS_PENDING,
    ACTION_STATUS_PREVIEWED,
    ASSET_ACTION_RELEASE,
    ASSET_ACTION_TRANSFER,
    ASSET_ACTION_VALUES,
    BATCH_PLAN_STATUS_ACTIVE,
    HandoverAppAction,
    HandoverAssetOverride,
    HandoverAssetType,
    HandoverBatchPlan,
    HandoverTask,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class OverrideEntry:
    asset_id: str
    action: str
    to_user_id: str | None
    label: str = ""


@dataclass(frozen=True, slots=True)
class PutOverridesResult:
    overrides_version: int
    confirm_version: int
    override_count: int
    dropped_invalid: int


def patch_asset_type_defaults(
    action: HandoverAppAction,
    *,
    type_key: str,
    default_action: str,
    default_to_user_id: str | None,
) -> tuple[HandoverAssetType, int]:
    """改类型级 default; 原子 CAS confirm_version +1。返回 (asset_type, new confirm_version)。"""
    if default_action not in ASSET_ACTION_VALUES:
        raise HandoverError("default_action 无效。")
    with transaction.atomic():
        locked = (
            HandoverAppAction.objects.select_for_update(of=("self",))
            .select_related("task", "task__subject_user")
            .get(pk=action.pk)
        )
        plan = _assert_mutable(locked)
        asset = (
            HandoverAssetType.objects.select_for_update()
            .filter(action=locked, generation=locked.generation, type_key=type_key)
            .first()
        )
        if asset is None:
            raise HandoverError("资产类型不存在。")
        if default_action != ASSET_ACTION_TRANSFER and default_to_user_id:
            raise HandoverError("receiver_not_allowed")
        default_to_user = _resolve_receiver(
            locked,
            default_to_user_id,
            required=default_action == ASSET_ACTION_TRANSFER,
        )
        if default_action == ASSET_ACTION_RELEASE and not asset.releasable:
            raise HandoverError("asset_type_not_releasable")
        asset.default_action = default_action
        asset.default_to_user = default_to_user
        asset.save(update_fields=["default_action", "default_to_user"])
        locked.confirm_version += 1
        if locked.status == ACTION_STATUS_PREVIEWED:
            # 分配变更不自动清 snapshot; confirm_version 负责击穿
            pass
        locked.save(update_fields=["confirm_version", "updated_at"])
        _replan_zero_progress_batch(locked, plan)
        return asset, locked.confirm_version


def put_overrides(
    action: HandoverAppAction,
    *,
    type_key: str,
    overrides_version: int,
    overrides: Sequence[OverrideEntry],
) -> PutOverridesResult:
    """校验完整集合后整体替换 overrides。"""
    with transaction.atomic():
        locked = locked_action_after_task(action)
        plan = _assert_mutable(locked)
        if overrides_version != locked.overrides_version:
            raise HandoverConflictError("overrides_version_stale")
        asset = (
            HandoverAssetType.objects.select_for_update()
            .filter(action=locked, generation=locked.generation, type_key=type_key)
            .first()
        )
        if asset is None:
            raise HandoverError("资产类型不存在。")

        seen_ids: set[str] = set()
        for entry in overrides:
            if entry.asset_id in seen_ids:
                raise HandoverError("duplicate_assignment")
            seen_ids.add(entry.asset_id)
            if not entry.asset_id:
                raise HandoverError("duplicate_assignment")
            if entry.action not in ASSET_ACTION_VALUES:
                raise HandoverError("invalid_assignment_action")
            if entry.action == ASSET_ACTION_RELEASE and not asset.releasable:
                raise HandoverError("asset_type_not_releasable")
            if entry.action == ASSET_ACTION_TRANSFER:
                if not entry.to_user_id:
                    raise HandoverError("receiver_required")
                _ = _resolve_receiver(locked, entry.to_user_id, required=True)
            elif entry.to_user_id:
                raise HandoverError("receiver_not_allowed")

        # 只有完整请求通过校验后才删除旧集合。
        _ = HandoverAssetOverride.objects.filter(asset_type=asset).delete()
        kept = 0
        for entry in overrides:
            to_user = None
            if entry.action == ASSET_ACTION_TRANSFER:
                to_user = _resolve_receiver(locked, entry.to_user_id, required=True)
            # 无明细时无法校验 asset_id 是否在下游存在; 整批保存, 失效在 execute 由下游 409。
            _ = HandoverAssetOverride.objects.create(
                asset_type=asset,
                asset_id=entry.asset_id[:128],
                label_snapshot=(entry.label or "")[:120],
                action=entry.action,
                to_user=to_user,
            )
            kept += 1

        locked.overrides_version += 1
        locked.confirm_version += 1
        locked.save(update_fields=["overrides_version", "confirm_version", "updated_at"])
        _replan_zero_progress_batch(locked, plan)
        return PutOverridesResult(
            overrides_version=locked.overrides_version,
            confirm_version=locked.confirm_version,
            override_count=kept,
            dropped_invalid=0,
        )


def list_overrides(action: HandoverAppAction, *, type_key: str) -> dict[str, object]:
    with transaction.atomic():
        locked = locked_action_after_task(action)
        asset = HandoverAssetType.objects.filter(
            action=locked,
            generation=locked.generation,
            type_key=type_key,
        ).first()
        if asset is None:
            raise HandoverError("资产类型不存在。")
        rows = []
        for ov in HandoverAssetOverride.objects.select_related("to_user").filter(
            asset_type=asset,
        ):
            rows.append(
                {
                    "asset_id": ov.asset_id,
                    "action": ov.action,
                    "to_user": (
                        {
                            "user_id": ov.to_user.authentik_user_id,
                            "name": ov.to_user.name,
                        }
                        if ov.to_user is not None
                        else None
                    ),
                    "label": ov.label_snapshot,
                },
            )
        return {
            "overrides_version": locked.overrides_version,
            "overrides": rows,
        }


def locked_action_after_task(action: HandoverAppAction) -> HandoverAppAction:
    _ = action.task_id
    _ = HandoverTask.objects.select_for_update().get(pk=action.task_id)
    return (
        HandoverAppAction.objects.select_for_update(of=("self",))
        .select_related("task", "task__subject_user")
        .get(pk=action.pk)
    )


def _assert_mutable(action: HandoverAppAction) -> HandoverBatchPlan | None:
    from easyauth.lifecycle.core import ensure_task_open

    ensure_task_open(action.task)
    if assignment_mutation_in_flight(action):
        raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
    if action.status in {ACTION_STATUS_PENDING, ACTION_STATUS_PREVIEWED, "failed", "blocked"}:
        pass
    else:
        raise HandoverConflictError("action_not_operable")
    plan = (
        HandoverBatchPlan.objects.select_for_update()
        .filter(
            action=action,
            generation=action.generation,
            status=BATCH_PLAN_STATUS_ACTIVE,
        )
        .first()
    )
    if plan is not None and plan.completed_batches > 0:
        raise HandoverConflictError("batch_plan_in_progress")
    return plan


def _replan_zero_progress_batch(
    action: HandoverAppAction,
    plan: HandoverBatchPlan | None,
) -> None:
    if plan is None:
        return
    # 01 §2.4.1.1: 修改与旧计划废弃、新 canonical assignment 重新规划同事务提交。
    from easyauth.lifecycle.handover_payloads import ensure_batch_plan_on_413

    _ = ensure_batch_plan_on_413(action)


def _resolve_receiver(
    action: HandoverAppAction,
    user_id: str | None,
    *,
    required: bool,
) -> UserMirror | None:
    if not user_id:
        if required:
            raise HandoverError("receiver_required")
        return None
    user = (
        UserMirror.objects.filter(authentik_user_id=user_id)
        .exclude(authentik_user_id__startswith=LOCAL_ADMIN_SUBJECT_PREFIX)
        .first()
    )
    if user is None or user.status != USER_STATUS_ACTIVE:
        raise HandoverError("receiver_not_active")
    if int(user.pk) == int(action.task.subject_user_id):  # type: ignore[arg-type]
        raise HandoverError("receiver_is_subject")
    return user
