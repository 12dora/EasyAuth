"""交接分配、执行摘要与条目接口契约校验。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, cast

from easyauth.accounts.models import USER_STATUS_ACTIVE
from easyauth.config.rate_limit import rate_limit_exceeded
from easyauth.lifecycle.core import (
    HOOK_EVENT_ITEMS,
    LIFECYCLE_ACTOR_ID,
    ensure_task_open,
)
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.models import (
    ACTION_FINISHED_STATUSES,
    ASSET_ACTION_RELEASE,
    ASSET_ACTION_TRANSFER,
    HANDOVER_KIND_OFFBOARD,
    HandoverAppAction,
    HandoverAssetOverride,
    HandoverAssetType,
)
from easyauth.webhooks.hooks import HookCallError, HookResponse, signed_hook_post

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror
    from easyauth.applications.ops_models import JsonValue

from easyauth.lifecycle.handover_shared import (
    DECLARED_WITHOUT_URL_MESSAGE,
    ITEMS_PAGE_MAX,
    ITEMS_PAGE_SIZE_MAX,
    ITEMS_QUERY_MAX_BYTES,
    ITEMS_RATE_LIMIT_MAX,
    ITEMS_RATE_LIMIT_NAMESPACE,
    ITEMS_RATE_LIMIT_WINDOW_SECONDS,
    RATE_LIMITED_MESSAGE,
    handover_hook_url,
    task_id,
)


def validate_assignments(action: HandoverAppAction) -> None:
    """execute 前置校验(01 §5.4)。不通过即 422, 不发 webhook。"""
    types = list(
        HandoverAssetType.objects.filter(
            action=action,
            generation=action.generation,
        ).prefetch_related("overrides"),
    )
    seen_type_keys: set[str] = set()
    for asset_type in types:
        if asset_type.type_key in seen_type_keys:
            raise HandoverError("duplicate_assignment")
        seen_type_keys.add(asset_type.type_key)
        _validate_asset_type_assignment(action, asset_type)
    if action.task.kind == HANDOVER_KIND_OFFBOARD and action.grant_receiver is not None:
        _assert_receiver_ok(action, action.grant_receiver)


def _validate_asset_type_assignment(
    action: HandoverAppAction,
    asset_type: HandoverAssetType,
) -> None:
    if asset_type.default_action == ASSET_ACTION_RELEASE and not asset_type.releasable:
        raise HandoverError("asset_type_not_releasable")
    if asset_type.default_action == ASSET_ACTION_TRANSFER:
        if asset_type.default_to_user is None:
            raise HandoverError("receiver_required")
        _assert_receiver_ok(action, asset_type.default_to_user)
    seen_ids: set[str] = set()
    for override in asset_type.overrides.all():
        if override.asset_id in seen_ids:
            raise HandoverError("duplicate_assignment")
        seen_ids.add(override.asset_id)
        _validate_override_assignment(action, asset_type, override)


def _validate_override_assignment(
    action: HandoverAppAction,
    asset_type: HandoverAssetType,
    override: HandoverAssetOverride,
) -> None:
    if override.action == ASSET_ACTION_RELEASE and not asset_type.releasable:
        raise HandoverError("asset_type_not_releasable")
    if override.action == ASSET_ACTION_TRANSFER:
        if override.to_user is None:
            raise HandoverError("receiver_required")
        _assert_receiver_ok(action, override.to_user)


def _validate_items_request(
    action: HandoverAppAction,
    *,
    page: int,
    page_size: int,
    q: str,
    actor_id: str,
) -> tuple[int, str]:
    ensure_task_open(action.task)
    if action.status in ACTION_FINISHED_STATUSES or action.data_completed_at is not None:
        raise HandoverConflictError("items_not_available")
    if page < 1 or page > ITEMS_PAGE_MAX:
        raise HandoverError("items_page_out_of_range")
    page_size = min(max(page_size, 1), ITEMS_PAGE_SIZE_MAX)
    q_stripped = q.strip()
    if len(q_stripped.encode("utf-8")) > ITEMS_QUERY_MAX_BYTES:
        raise HandoverError("items_query_too_long")
    rate_identity = f"{actor_id}:{action.task_id}:{action.app_id}"
    if rate_limit_exceeded(
        ITEMS_RATE_LIMIT_NAMESPACE,
        rate_identity,
        limit=ITEMS_RATE_LIMIT_MAX,
        window_seconds=ITEMS_RATE_LIMIT_WINDOW_SECONDS,
    ):
        raise HandoverConflictError(RATE_LIMITED_MESSAGE)
    return page_size, q_stripped


def _items_asset(action: HandoverAppAction, asset_type: str) -> HandoverAssetType:
    asset = HandoverAssetType.objects.filter(
        action=action,
        generation=action.generation,
        type_key=asset_type,
    ).first()
    if asset is None or not asset.detail_supported:
        raise HandoverError("detail_not_supported")
    return asset


def _items_response_body(response: HookResponse) -> dict[str, JsonValue]:
    if response.status_code != HTTPStatus.OK:
        raise HookCallError(
            f"items 接口返回 {response.status_code}",
            status_code=response.status_code,
            payload=response.payload,
            raw_body=response.raw_body,
            location=response.location,
        )
    return response.payload


@dataclass(frozen=True, slots=True)
class FetchActionItemsSpec:
    """条目查询所需参数。"""

    asset_type: str
    page: int
    page_size: int
    q: str
    actor_id: str = LIFECYCLE_ACTOR_ID


def fetch_action_items(
    action: HandoverAppAction,
    spec: FetchActionItemsSpec,
) -> dict[str, JsonValue]:
    """透传 items; 参数上界与限流(01 §5.6)。"""
    page_size, q_stripped = _validate_items_request(
        action,
        page=spec.page,
        page_size=spec.page_size,
        q=spec.q,
        actor_id=spec.actor_id,
    )
    asset = _items_asset(action, spec.asset_type)
    hook_url = handover_hook_url(action.app)
    if not hook_url:
        raise HandoverError(DECLARED_WITHOUT_URL_MESSAGE)
    payload: dict[str, JsonValue] = {
        "task_id": task_id(action),
        "event_type": HOOK_EVENT_ITEMS,
        "kind": action.task.kind,
        "from_user_id": action.task.subject_user.authentik_user_id,
        "generation": action.generation,
        "snapshot_token": action.snapshot_token,
        "asset_type": spec.asset_type,
        "page": spec.page,
        "page_size": page_size,
        "q": q_stripped,
    }
    response = signed_hook_post(
        app=action.app,
        url=hook_url,
        event_type=HOOK_EVENT_ITEMS,
        delivery_id=uuid.uuid4().hex,
        payload=payload,
    )
    body = _items_response_body(response)
    total = int(body.get("total", 0) or 0)
    unfiltered = body.get("unfiltered_total")
    stale = False
    if q_stripped == "" and total != asset.count:
        stale = True
    elif q_stripped and unfiltered is not None and int(unfiltered) != asset.count:
        stale = True
    return {
        "items": body.get("items", []),
        "page": spec.page,
        "page_size": page_size,
        "total": total,
        "unfiltered_total": unfiltered,
        "stale": stale,
    }


_SUMMARY_CONSERVATION_FIELDS: Final = ("transferred", "released", "skipped", "merged", "failed")


def _missing_summary_error(action: HandoverAppAction) -> str | None:
    """无 summary 键: 仅当全部类型 count=0 时允许(零资产 no-op)。"""
    types_all = list(
        HandoverAssetType.objects.filter(
            action=action,
            generation=action.generation,
        ),
    )
    if any(int(at.count) > 0 for at in types_all):
        return "execute 响应缺少 summary"
    return None


def _summary_row_shape_error(
    type_key: str,
    row: dict[str, JsonValue],
    *,
    types: dict[str, HandoverAssetType],
) -> str | None:
    """校验 summary 行: 必须命中已知资产类型, 且恰好携带冻结五元组的非负整数。"""
    frozen_fields = set(_SUMMARY_CONSERVATION_FIELDS)
    if type_key not in types:
        return f"summary 含未知资产类型 {type_key}"
    if set(row) != frozen_fields:
        return f"summary[{type_key}] 必须且只能包含冻结五元组"
    for field in _SUMMARY_CONSERVATION_FIELDS:
        val = row[field]
        if type(val) is not int or val < 0:
            return f"summary[{type_key}].{field} 非法"
    return None


def _summary_row_error(
    type_key: object,
    row: object,
    *,
    types: dict[str, HandoverAssetType],
) -> str | None:
    """单个资产类型的 summary 行形状 / failed / 守恒校验; 通过返回 None。"""
    if not isinstance(type_key, str) or not isinstance(row, dict):
        return f"summary[{type_key!r}] 形状非法"
    summary_row = cast("dict[str, JsonValue]", row)
    shape_error = _summary_row_shape_error(type_key, summary_row, types=types)
    if shape_error is not None:
        return shape_error
    counts = [cast("int", summary_row[field]) for field in _SUMMARY_CONSERVATION_FIELDS]
    transferred, released, skipped, merged, failed = counts
    if failed > 0:
        return f"summary[{type_key}].failed={failed} (部分成功视为失败)"
    total = transferred + released + skipped + merged + failed
    expected = int(types[type_key].count)
    if total != expected:
        return (
            f"summary[{type_key}] 不守恒: "
            f"{transferred}+{released}+{skipped}+{merged}+{failed}={total} != count={expected}"
        )
    return None


def validate_execute_summary_conservation(
    action: HandoverAppAction,
    *,
    response_payload: dict[str, JsonValue] | None,
) -> str | None:
    """00 §10.5: transferred+released+skipped+merged+failed == preview count。

    不守恒或 failed>0 → 返回错误文案; 通过返回 None。
    """
    if response_payload is None:
        return "execute 响应缺少 payload"
    raw_summary = response_payload.get("summary")
    if raw_summary is None:
        return _missing_summary_error(action)
    if not isinstance(raw_summary, dict):
        return "execute 响应 summary 形状非法"
    types = {
        at.type_key: at
        for at in HandoverAssetType.objects.filter(
            action=action,
            generation=action.generation,
        )
    }
    for type_key, row in raw_summary.items():
        error = _summary_row_error(type_key, row, types=types)
        if error is not None:
            return error
    # preview 有 count>0 的类型必须出现在 summary
    for type_key, asset in types.items():
        if asset.count > 0 and type_key not in raw_summary:
            return f"summary 缺少资产类型 {type_key} (count={asset.count})"
    return None


def merge_result_summary(
    action: HandoverAppAction,
    response_payload: dict[str, JsonValue],
) -> None:
    raw = response_payload.get("summary")
    if not isinstance(raw, dict):
        return
    current = action.result_summary if isinstance(action.result_summary, dict) else {}
    merged: dict[str, JsonValue] = dict(current)
    for type_key, row in raw.items():
        if not isinstance(type_key, str) or not isinstance(row, dict):
            continue
        prev = merged.get(type_key)
        base = (
            dict(prev)
            if isinstance(prev, dict)
            else {"transferred": 0, "released": 0, "skipped": 0, "merged": 0, "failed": 0}
        )
        for field in ("transferred", "released", "skipped", "merged", "failed"):
            prev_val = base.get(field, 0)
            add_val = row.get(field, 0)
            base[field] = (int(prev_val) if isinstance(prev_val, int) else 0) + (
                int(add_val) if isinstance(add_val, int) else 0
            )
        merged[type_key] = cast("JsonValue", base)
    action.result_summary = merged


def _assert_receiver_ok(action: HandoverAppAction, user: UserMirror) -> None:
    if user.status != USER_STATUS_ACTIVE:
        raise HandoverError("receiver_not_active")
    if cast("int", user.pk) == action.task.subject_user_id:
        raise HandoverError("receiver_is_subject")
