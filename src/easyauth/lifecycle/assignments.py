"""资产类型默认分配与 overrides 整体替换(01 §5.4 / §6)。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from django.db import transaction

from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.lifecycle.core import ensure_task_open
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover_payloads import ensure_batch_plan_on_413
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


_DEFAULT_ACTION_INVALID_MESSAGE: Final = "default_action 无效。"
_ASSET_TYPE_NOT_FOUND_MESSAGE: Final = "资产类型不存在。"
_RECEIVER_NOT_ALLOWED_MESSAGE: Final = "receiver_not_allowed"
_ASSET_TYPE_NOT_RELEASABLE_MESSAGE: Final = "asset_type_not_releasable"
_OVERRIDES_VERSION_STALE_MESSAGE: Final = "overrides_version_stale"
_DUPLICATE_ASSIGNMENT_MESSAGE: Final = "duplicate_assignment"
_INVALID_ASSIGNMENT_ACTION_MESSAGE: Final = "invalid_assignment_action"
_RECEIVER_REQUIRED_MESSAGE: Final = "receiver_required"
_ACTION_NOT_OPERABLE_MESSAGE: Final = "action_not_operable"
_BATCH_PLAN_IN_PROGRESS_MESSAGE: Final = "batch_plan_in_progress"
_RECEIVER_NOT_ACTIVE_MESSAGE: Final = "receiver_not_active"
_RECEIVER_IS_SUBJECT_MESSAGE: Final = "receiver_is_subject"


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
        raise HandoverError(_DEFAULT_ACTION_INVALID_MESSAGE)
    with transaction.atomic():
        locked = (
            HandoverAppAction.objects.select_for_update(of=("self",))
            .select_related("task", "task__subject_user")
            .get(pk=action.id)
        )
        plan = _assert_mutable(locked)
        asset = (
            HandoverAssetType.objects.select_for_update()
            .filter(action=locked, generation=locked.generation, type_key=type_key)
            .first()
        )
        if asset is None:
            raise HandoverError(_ASSET_TYPE_NOT_FOUND_MESSAGE)
        if default_action != ASSET_ACTION_TRANSFER and default_to_user_id:
            raise HandoverError(_RECEIVER_NOT_ALLOWED_MESSAGE)
        default_to_user = _resolve_receiver(
            locked,
            default_to_user_id,
            required=default_action == ASSET_ACTION_TRANSFER,
        )
        if default_action == ASSET_ACTION_RELEASE and not asset.releasable:
            raise HandoverError(_ASSET_TYPE_NOT_RELEASABLE_MESSAGE)
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
            raise HandoverConflictError(_OVERRIDES_VERSION_STALE_MESSAGE)
        asset = (
            HandoverAssetType.objects.select_for_update()
            .filter(action=locked, generation=locked.generation, type_key=type_key)
            .first()
        )
        if asset is None:
            raise HandoverError(_ASSET_TYPE_NOT_FOUND_MESSAGE)
        _validate_overrides(locked, asset=asset, overrides=overrides)
        kept = _replace_overrides(locked, asset=asset, overrides=overrides)

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


def _validate_overrides(
    action: HandoverAppAction,
    *,
    asset: HandoverAssetType,
    overrides: Sequence[OverrideEntry],
) -> None:
    seen_ids: set[str] = set()
    for entry in overrides:
        _validate_override(action, asset=asset, entry=entry, seen_ids=seen_ids)


def _validate_override(
    action: HandoverAppAction,
    *,
    asset: HandoverAssetType,
    entry: OverrideEntry,
    seen_ids: set[str],
) -> None:
    if entry.asset_id in seen_ids:
        raise HandoverError(_DUPLICATE_ASSIGNMENT_MESSAGE)
    seen_ids.add(entry.asset_id)
    if not entry.asset_id:
        raise HandoverError(_DUPLICATE_ASSIGNMENT_MESSAGE)
    if entry.action not in ASSET_ACTION_VALUES:
        raise HandoverError(_INVALID_ASSIGNMENT_ACTION_MESSAGE)
    if entry.action == ASSET_ACTION_RELEASE and not asset.releasable:
        raise HandoverError(_ASSET_TYPE_NOT_RELEASABLE_MESSAGE)
    if entry.action == ASSET_ACTION_TRANSFER:
        if not entry.to_user_id:
            raise HandoverError(_RECEIVER_REQUIRED_MESSAGE)
        _ = _resolve_receiver(action, entry.to_user_id, required=True)
    elif entry.to_user_id:
        raise HandoverError(_RECEIVER_NOT_ALLOWED_MESSAGE)


def _replace_overrides(
    action: HandoverAppAction,
    *,
    asset: HandoverAssetType,
    overrides: Sequence[OverrideEntry],
) -> int:
    # 只有完整请求通过校验后才删除旧集合。
    _ = HandoverAssetOverride.objects.filter(asset_type=asset).delete()
    kept = 0
    for entry in overrides:
        _create_override(action, asset=asset, entry=entry)
        kept += 1
    return kept


def _create_override(
    action: HandoverAppAction,
    *,
    asset: HandoverAssetType,
    entry: OverrideEntry,
) -> None:
    to_user = None
    if entry.action == ASSET_ACTION_TRANSFER:
        to_user = _resolve_receiver(action, entry.to_user_id, required=True)
    # 无明细时无法校验 asset_id 是否在下游存在; 整批保存, 失效在 execute 由下游 409。
    _ = HandoverAssetOverride.objects.create(
        asset_type=asset,
        asset_id=entry.asset_id[:128],
        label_snapshot=(entry.label or "")[:120],
        action=entry.action,
        to_user=to_user,
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
            raise HandoverError(_ASSET_TYPE_NOT_FOUND_MESSAGE)
        rows = [
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
            }
            for ov in HandoverAssetOverride.objects.select_related("to_user").filter(
                asset_type=asset,
            )
        ]
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
        .get(pk=action.id)
    )


def _assert_mutable(action: HandoverAppAction) -> HandoverBatchPlan | None:
    ensure_task_open(action.task)
    if assignment_mutation_in_flight(action):
        raise HandoverConflictError(HANDOVER_EXECUTION_IN_FLIGHT)
    if action.status in {ACTION_STATUS_PENDING, ACTION_STATUS_PREVIEWED, "failed", "blocked"}:
        pass
    else:
        raise HandoverConflictError(_ACTION_NOT_OPERABLE_MESSAGE)
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
        raise HandoverConflictError(_BATCH_PLAN_IN_PROGRESS_MESSAGE)
    return plan


def _replan_zero_progress_batch(
    action: HandoverAppAction,
    plan: HandoverBatchPlan | None,
) -> None:
    if plan is None:
        return
    # 01 §2.4.1.1: 修改与旧计划废弃、新 canonical assignment 重新规划同事务提交。
    _ = ensure_batch_plan_on_413(action)


def _resolve_receiver(
    action: HandoverAppAction,
    user_id: str | None,
    *,
    required: bool,
) -> UserMirror | None:
    if not user_id:
        if required:
            raise HandoverError(_RECEIVER_REQUIRED_MESSAGE)
        return None
    user = (
        UserMirror.objects.filter(authentik_user_id=user_id)
        .exclude(authentik_user_id__startswith=LOCAL_ADMIN_SUBJECT_PREFIX)
        .first()
    )
    if user is None or user.status != USER_STATUS_ACTIVE:
        raise HandoverError(_RECEIVER_NOT_ACTIVE_MESSAGE)
    if user.id == action.task.subject_user_id:
        raise HandoverError(_RECEIVER_IS_SUBJECT_MESSAGE)
    return user
