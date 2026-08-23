"""交接预演请求的预留、投递与结果落库。"""

from __future__ import annotations

import uuid
from http import HTTPStatus
from typing import TYPE_CHECKING, Final

from django.db import transaction

from easyauth.applications.models import (
    HANDOVER_CAPABILITY_DECLARED,
)
from easyauth.lifecycle.core import (
    HOOK_EVENT_PREVIEW,
    LIFECYCLE_ACTOR_ID,
    PREVIEW_GENERATION_CONFLICT_MESSAGE,
    PREVIEW_SYNC_REQUIRED_MESSAGE,
    ensure_action_status,
    record_task_event,
    refresh_task_status_locked,
)
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover_payloads import (
    build_preview_payload,
)
from easyauth.lifecycle.handover_shared import (
    DECLARED_WITHOUT_URL_MESSAGE,
    SNAPSHOT_TOKEN_MAX_LEN,
    ActionErrorContext,
    MutationGuard,
    PreviewRequest,
    handover_hook_url,
    locked_action_after_task,
    set_action_error,
)
from easyauth.lifecycle.models import (
    ACTION_STATUS_FAILED,
    ACTION_STATUS_PENDING,
    ACTION_STATUS_PREVIEWED,
    HandoverAppAction,
    HandoverAssetType,
    HandoverTask,
)
from easyauth.webhooks.hooks import HookCallError, HookResponse, signed_hook_post

if TYPE_CHECKING:
    from easyauth.applications.ops_models import JsonValue


_ACTION_BLOCKED_MESSAGE: Final = "action_blocked"
_PREVIEW_RESULT_MISSING_MESSAGE: Final = "预演完成后缺少动作结果。"
_PREVIEW_ASSETS_MISSING_MESSAGE: Final = "preview 响应缺少 assets"


def preview_action(
    action: HandoverAppAction,
    *,
    mutation_guard: MutationGuard | None = None,
) -> HandoverAppAction:
    request = _reserve_preview_request(action.id, mutation_guard=mutation_guard)
    if not request.hook_url:
        raise HandoverError(DECLARED_WITHOUT_URL_MESSAGE)
    try:
        response = signed_hook_post(
            app=request.app,
            url=request.hook_url,
            event_type=HOOK_EVENT_PREVIEW,
            delivery_id=uuid.uuid4().hex,
            payload=request.payload,
        )
        payload = _preview_response_payload(response)
    except HookCallError as error:
        _record_preview_error(request, error)
        raise
    return _complete_preview_request(request, payload=payload)


def _reserve_preview_request(
    action_id: int,
    *,
    mutation_guard: MutationGuard | None = None,
) -> PreviewRequest:
    with transaction.atomic():
        action = locked_action_after_task(action_id)
        if mutation_guard is not None:
            mutation_guard(action)
        ensure_action_status(
            action,
            allowed={ACTION_STATUS_PENDING, ACTION_STATUS_PREVIEWED},
        )
        if action.app.handover_capability != HANDOVER_CAPABILITY_DECLARED:
            raise HandoverConflictError(_ACTION_BLOCKED_MESSAGE)
        action.preview_generation += 1
        action.save(update_fields=["preview_generation", "updated_at"])
        hook_url = handover_hook_url(action.app)
        if not hook_url:
            raise HandoverError(DECLARED_WITHOUT_URL_MESSAGE)
        return PreviewRequest(
            action_id=action.id,
            preview_generation=action.preview_generation,
            generation=action.generation,
            app=action.app,
            hook_url=hook_url,
            payload=build_preview_payload(action),
        )


def _record_preview_error(request: PreviewRequest, error: Exception) -> None:
    with transaction.atomic():
        action = _locked_preview_action(request)
        if action is None:
            return
        set_action_error(
            action,
            error,
            ActionErrorContext(
                status_code=error.status_code if isinstance(error, HookCallError) else None,
                payload=error.payload if isinstance(error, HookCallError) else None,
                raw_body=error.raw_body if isinstance(error, HookCallError) else "",
            ),
        )
        action.save(update_fields=["last_error", "last_error_raw", "updated_at"])
        task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
        _ = refresh_task_status_locked(task)


def _complete_preview_request(
    request: PreviewRequest,
    *,
    payload: dict[str, JsonValue],
) -> HandoverAppAction:
    preview_error: HandoverError | None = None
    result: HandoverAppAction | None = None
    with transaction.atomic():
        action = _locked_preview_action(request)
        if action is None:
            raise HandoverConflictError(PREVIEW_GENERATION_CONFLICT_MESSAGE)
        ensure_action_status(action, allowed={ACTION_STATUS_PENDING, ACTION_STATUS_PREVIEWED})
        try:
            result = _apply_preview_success(action, payload)
        except HandoverError as error:
            # failed 必须提交后再 raise, 不能被 atomic 回滚。
            _apply_preview_failure(action, error)
            preview_error = error
    if preview_error is not None:
        raise preview_error
    if result is None:
        raise AssertionError(_PREVIEW_RESULT_MISSING_MESSAGE)
    return result


def _apply_preview_success(
    action: HandoverAppAction,
    payload: dict[str, JsonValue],
) -> HandoverAppAction:
    _apply_preview_assets(action, payload)
    token = str(payload.get("snapshot_token", "") or "")
    if len(token) > SNAPSHOT_TOKEN_MAX_LEN:
        message = f"snapshot_token 超过 {SNAPSHOT_TOKEN_MAX_LEN} 字节上限"
        raise HandoverError(message)
    action.snapshot_token = token
    action.status = ACTION_STATUS_PREVIEWED
    action.last_error = ""
    action.confirm_version += 1
    action.save(
        update_fields=["snapshot_token", "status", "last_error", "confirm_version", "updated_at"],
    )
    record_task_event(
        action.task,
        action="handover_action_previewed",
        actor_id=LIFECYCLE_ACTOR_ID,
        actor_type="system",
        extra={"app_key": action.app_key_snapshot},
    )
    task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
    _ = refresh_task_status_locked(task)
    return action


def _apply_preview_failure(action: HandoverAppAction, error: HandoverError) -> None:
    action.status = ACTION_STATUS_FAILED
    set_action_error(
        action,
        error,
        ActionErrorContext(
            status_code=error.status_code if isinstance(error, HookCallError) else None,
            payload=error.payload if isinstance(error, HookCallError) else None,
            raw_body=error.raw_body if isinstance(error, HookCallError) else "",
        ),
    )
    action.save(update_fields=["status", "last_error", "last_error_raw", "updated_at"])
    task = HandoverTask.objects.select_for_update().get(pk=action.task_id)
    _ = refresh_task_status_locked(task)


def _locked_preview_action(request: PreviewRequest) -> HandoverAppAction | None:
    return (
        HandoverAppAction.objects.select_for_update(of=("self",))
        .select_related("app", "task", "task__subject_user", "grant_receiver")
        .filter(
            pk=request.action_id,
            preview_generation=request.preview_generation,
            generation=request.generation,
        )
        .first()
    )


def _apply_preview_assets(action: HandoverAppAction, payload: dict[str, JsonValue]) -> None:
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise HandoverError(_PREVIEW_ASSETS_MISSING_MESSAGE)
    declared = {
        str(item.get("type", "")): item
        for item in (action.app.handover_asset_types or [])
        if isinstance(item, dict)
    }
    seen: set[str] = set()
    for raw in assets:
        if not isinstance(raw, dict):
            continue
        type_key = str(raw.get("type", ""))
        if not type_key:
            continue
        if type_key not in declared:
            message = f"undeclared_asset_type: {type_key}"
            raise HandoverError(message)
        seen.add(type_key)
        _apply_preview_asset_row(action, raw, type_key=type_key, declared=declared[type_key])
    missing = set(declared) - seen
    if missing:
        message = f"preview 缺少已声明类型: {', '.join(sorted(missing))}"
        raise HandoverError(message)


def _apply_preview_asset_row(
    action: HandoverAppAction,
    raw: dict[str, JsonValue],
    *,
    type_key: str,
    declared: dict[str, JsonValue],
) -> None:
    existing = HandoverAssetType.objects.filter(
        action=action,
        generation=action.generation,
        type_key=type_key,
    ).first()
    label = str(raw.get("label", type_key))[:120]
    invalid_count_message = f"invalid_asset_count: {type_key}"
    try:
        count = int(raw.get("count", 0) or 0)
    except (TypeError, ValueError) as error:
        raise HandoverError(invalid_count_message) from error
    if count < 0:
        raise HandoverError(invalid_count_message)
    detail = bool(raw.get("detail_supported", declared.get("detail_supported", False)))
    releasable = bool(raw.get("releasable", declared.get("releasable", False)))
    if existing is None:
        _ = HandoverAssetType.objects.create(
            action=action,
            generation=action.generation,
            type_key=type_key,
            label_snapshot=label,
            count=count,
            detail_supported=detail,
            releasable=releasable,
        )
        return
    existing.label_snapshot = label
    existing.count = count
    existing.detail_supported = detail
    existing.releasable = releasable
    existing.save(
        update_fields=["label_snapshot", "count", "detail_supported", "releasable"],
    )


def _preview_response_payload(response: HookResponse) -> dict[str, JsonValue]:
    if response.status_code != HTTPStatus.OK:
        raise HookCallError(
            PREVIEW_SYNC_REQUIRED_MESSAGE,
            status_code=response.status_code,
            payload=response.payload,
            raw_body=response.raw_body,
            location=response.location,
        )
    return response.payload
