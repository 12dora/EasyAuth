from __future__ import annotations

import uuid
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from django.db import transaction
from django.db.models import Q

from easyauth.lifecycle.core import (
    ACTION_NOT_OPERABLE_MESSAGE,
    ACTION_RECEIVER_FROZEN_MESSAGE,
    ACTION_SELF_RECEIVER_MESSAGE,
    ASYNC_ACCEPTED_LOCATION_REQUIRED_MESSAGE,
    ASYNC_POLL_LIMIT_MESSAGE,
    ASYNC_POLL_MAX_ATTEMPTS,
    ASYNC_STATUS_URL_REQUIRED_MESSAGE,
    EXECUTE_ACCEPTED_LOCATION_REQUIRED_MESSAGE,
    HOOK_EVENT_EXECUTE,
    HOOK_EVENT_PREVIEW,
    HOOK_NOT_DECLARED_RESULT,
    LIFECYCLE_ACTOR_ID,
    PREVIEW_GENERATION_CONFLICT_MESSAGE,
    PREVIEW_SYNC_REQUIRED_MESSAGE,
    TASK_NOT_DELETABLE_MESSAGE,
    ensure_action_status,
    ensure_task_open,
    record_task_event,
    refresh_task_status,
    validate_receiver_strategy,
)
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.models import (
    ACTION_STATUS_ASYNC_PENDING,
    ACTION_STATUS_DONE,
    ACTION_STATUS_EXECUTING,
    ACTION_STATUS_FAILED,
    ACTION_STATUS_PENDING,
    ACTION_STATUS_PREVIEWED,
    ACTION_STATUS_SKIPPED,
    ITEM_STATUS_DONE,
    ITEM_STATUS_PENDING,
    ITEM_STATUS_SKIPPED,
    TASK_STATUS_CANCELLED,
    TEAM_ITEM_ACTION_ASSIGN_LEADER,
    TEAM_ITEM_ACTION_DEACTIVATE,
    HandoverAppAction,
    HandoverGrantItem,
    HandoverTask,
    HandoverTeamItem,
)
from easyauth.lifecycle.transfer import transfer_selected_grants
from easyauth.teams.models import TEAM_MEMBER_ROLE_LEADER, TeamMember
from easyauth.webhooks.hooks import HookCallError, HookResponse, signed_hook_get, signed_hook_post
from easyauth.webhooks.models import AppWebhookConfig

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror
    from easyauth.applications.models import App
    from easyauth.applications.ops_models import JsonValue



@dataclass(frozen=True, slots=True)
class _PreviewRequest:
    action_id: int
    generation: int
    app: App
    hook_url: str
    payload: dict[str, JsonValue]










def update_action_receiver(
    *,
    action: HandoverAppAction,
    to_user: UserMirror | None,
    policy: dict[str, JsonValue],
) -> HandoverAppAction:
    with transaction.atomic():
        locked = _locked_action(action.id)
        ensure_task_open(locked.task)
        validate_receiver_strategy(locked, to_user=to_user, policy=policy)
        has_processed_items = (
            HandoverGrantItem.objects.filter(
                task=locked.task,
                app=locked.app,
            )
            .exclude(status=ITEM_STATUS_PENDING)
            .exists()
        )
        if locked.attempts or has_processed_items:
            to_user_pk = cast("int | None", to_user.pk if to_user is not None else None)
            if locked.to_user_id != to_user_pk or (
                locked.policy != policy
            ):
                raise HandoverConflictError(ACTION_RECEIVER_FROZEN_MESSAGE)
            return locked
        locked.to_user = to_user
        locked.policy = policy
        if locked.status in {ACTION_STATUS_FAILED, ACTION_STATUS_PREVIEWED}:
            # 执行前改接收策略时旧预览作废。
            locked.status = ACTION_STATUS_PENDING
            locked.preview_payload = {}
            locked.last_error = ""
        locked.save()
        return locked


def preview_action(action: HandoverAppAction) -> HandoverAppAction:
    """调 APP 钩子 preview(不落库业务数据), 只报影响面。"""
    request = _reserve_preview_request(action.id)
    if not request.hook_url:
        payload: dict[str, JsonValue] = {"assets": [], "hook": HOOK_NOT_DECLARED_RESULT}
    else:
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


def execute_action(action: HandoverAppAction) -> HandoverAppAction:
    return _execute_action(action, allowed_status=ACTION_STATUS_PREVIEWED)


def retry_action(action: HandoverAppAction) -> HandoverAppAction:
    return _execute_action(action, allowed_status=ACTION_STATUS_FAILED)


def _execute_action(
    action: HandoverAppAction,
    *,
    allowed_status: str,
) -> HandoverAppAction:
    """执行单个 APP 的交接: 转授勾选权限(EasyAuth 内部) + 调 APP 钩子交接数据。

    幂等以 task_id 为键(APP 侧承诺重复 execute 安全); 失败置 failed 可重试,
    单 APP 失败不影响其他 APP。
    """
    with transaction.atomic():
        action = _locked_action(action.id)
        ensure_action_status(action, allowed={allowed_status})
        validate_receiver_strategy(action, to_user=action.to_user, policy=action.policy)
        if action.attempts == 0:
            action.execution_to_user = action.to_user
            action.execution_policy = dict(action.policy)
        elif (
            action.execution_to_user_id != action.to_user_id
            or action.execution_policy != action.policy
        ):
            raise HandoverConflictError(ACTION_RECEIVER_FROZEN_MESSAGE)
        action.status = ACTION_STATUS_EXECUTING
        action.attempts += 1
        action.save(
            update_fields=[
                "execution_to_user",
                "execution_policy",
                "status",
                "attempts",
                "updated_at",
            ],
        )

    try:
        transferred = transfer_selected_grants(action)
        hook_url = _handover_hook_url(action.app)
        if hook_url:
            response = signed_hook_post(
                app=action.app,
                url=hook_url,
                event_type=HOOK_EVENT_EXECUTE,
                delivery_id=uuid.uuid4().hex,
                payload=_hook_payload(action, mode="execute"),
            )
            if response.status_code == HTTPStatus.ACCEPTED:
                _ensure_accepted_location(
                    response,
                    message=EXECUTE_ACCEPTED_LOCATION_REQUIRED_MESSAGE,
                )
                with transaction.atomic():
                    action = _locked_action(action.id)
                    if action.status != ACTION_STATUS_EXECUTING:
                        raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
                    action.result_payload = response.payload
                    action.async_status_url = response.location
                    action.status = ACTION_STATUS_ASYNC_PENDING
                    action.last_error = ""
                    action.save(
                        update_fields=[
                            "result_payload",
                            "async_status_url",
                            "status",
                            "last_error",
                            "updated_at",
                        ],
                    )
                record_task_event(
                    action.task,
                    action="handover_action_async_pending",
                    actor_id=LIFECYCLE_ACTOR_ID,
                    extra={"app_key": action.app_key_snapshot},
                )
                _ = refresh_task_status(action.task)
                return action
            result = _execute_response_payload(response)
        else:
            result = _hook_skipped_result()
    except (HookCallError, HandoverError) as error:
        _finish_action_failure(action.id, error)
        record_task_event(
            action.task,
            action="handover_action_failed",
            actor_id=LIFECYCLE_ACTOR_ID,
            extra={"app_key": action.app.app_key, "error": str(error)},
        )
        raise

    with transaction.atomic():
        action = _locked_action(action.id)
        if action.status != ACTION_STATUS_EXECUTING:
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        action.result_payload = result
        action.status = ACTION_STATUS_DONE
        action.last_error = ""
        action.save(update_fields=["result_payload", "status", "last_error", "updated_at"])
    record_task_event(
        action.task,
        action="handover_action_executed",
        actor_id=LIFECYCLE_ACTOR_ID,
        extra={
            "app_key": action.app.app_key,
            "transferred_grant_items": transferred,
            "to_user_id": (
                action.execution_to_user.authentik_user_id
                if action.execution_to_user is not None
                else ""
            ),
        },
    )
    _ = refresh_task_status(action.task)
    return action


def poll_async_action(action: HandoverAppAction) -> HandoverAppAction:
    with transaction.atomic():
        action = _locked_action(action.id)
        ensure_action_status(action, allowed={ACTION_STATUS_ASYNC_PENDING})
        if not action.async_status_url:
            raise HandoverConflictError(ASYNC_STATUS_URL_REQUIRED_MESSAGE)
        if action.async_poll_attempts >= ASYNC_POLL_MAX_ATTEMPTS:
            raise HandoverConflictError(ASYNC_POLL_LIMIT_MESSAGE)
        action.async_poll_attempts += 1
        action.save(update_fields=["async_poll_attempts", "updated_at"])
    try:
        response = signed_hook_get(
            app=action.app,
            url=action.async_status_url,
            event_type=HOOK_EVENT_EXECUTE,
            delivery_id=uuid.uuid4().hex,
        )
        _validate_poll_response(response)
    except (HookCallError, HandoverError) as error:
        with transaction.atomic():
            action = _locked_action(action.id)
            if action.status == ACTION_STATUS_ASYNC_PENDING:
                action.last_error = str(error)
                action.save(update_fields=["last_error", "updated_at"])
        raise
    with transaction.atomic():
        action = _locked_action(action.id)
        if action.status != ACTION_STATUS_ASYNC_PENDING:
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        action.result_payload = response.payload
        action.last_error = ""
        if response.status_code == HTTPStatus.ACCEPTED:
            action.async_status_url = response.location
            action.save(
                update_fields=[
                    "result_payload",
                    "async_status_url",
                    "last_error",
                    "updated_at",
                ],
            )
            return action
        action.status = ACTION_STATUS_DONE
        action.async_status_url = ""
        action.save(
            update_fields=[
                "result_payload",
                "status",
                "async_status_url",
                "last_error",
                "updated_at",
            ],
        )
    record_task_event(
        action.task,
        action="handover_action_async_completed",
        actor_id=LIFECYCLE_ACTOR_ID,
        extra={"app_key": action.app_key_snapshot},
    )
    _ = refresh_task_status(action.task)
    return action


def _hook_skipped_result() -> dict[str, JsonValue]:
    return {"hook": HOOK_NOT_DECLARED_RESULT}


def _preview_response_payload(response: HookResponse) -> dict[str, JsonValue]:
    if response.status_code != HTTPStatus.OK:
        raise HandoverError(PREVIEW_SYNC_REQUIRED_MESSAGE)
    return response.payload


def _ensure_accepted_location(response: HookResponse, *, message: str) -> None:
    if not response.location:
        raise HandoverError(message)


def _execute_response_payload(response: HookResponse) -> dict[str, JsonValue]:
    if response.status_code != HTTPStatus.OK:
        message = f"应用交接接口返回不支持的成功状态 {response.status_code}。"
        raise HandoverError(message)
    return response.payload


def _validate_poll_response(response: HookResponse) -> None:
    if response.status_code not in {HTTPStatus.OK, HTTPStatus.ACCEPTED}:
        message = f"应用交接状态接口返回不支持的成功状态 {response.status_code}。"
        raise HandoverError(message)
    if response.status_code == HTTPStatus.ACCEPTED:
        _ensure_accepted_location(
            response,
            message=ASYNC_ACCEPTED_LOCATION_REQUIRED_MESSAGE,
        )


def skip_action(action: HandoverAppAction, *, actor_id: str) -> HandoverAppAction:
    with transaction.atomic():
        action = _locked_action(action.id)
        ensure_action_status(
            action,
            allowed={ACTION_STATUS_PENDING, ACTION_STATUS_PREVIEWED, ACTION_STATUS_FAILED},
        )
        if (
            action.attempts
            or HandoverGrantItem.objects.filter(
                task=action.task,
                app=action.app,
            )
            .exclude(status=ITEM_STATUS_PENDING)
            .exists()
        ):
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        action.status = ACTION_STATUS_SKIPPED
        action.save(update_fields=["status", "updated_at"])
        _ = HandoverGrantItem.objects.filter(
            task=action.task,
            app=action.app,
            status=ITEM_STATUS_PENDING,
        ).update(status=ITEM_STATUS_SKIPPED)
    record_task_event(
        action.task,
        action="handover_action_skipped",
        actor_id=actor_id,
        extra={"app_key": action.app.app_key},
    )
    _ = refresh_task_status(action.task)
    return action


def apply_team_item(
    *,
    item: HandoverTeamItem,
    action: str,
    to_user: UserMirror | None,
    actor_id: str,
) -> HandoverTeamItem:
    """团队交接立即执行: 接收人接任 leader 或团队停用(§4.5)。"""
    with transaction.atomic():
        item = (
            HandoverTeamItem.objects.select_for_update()
            .select_related("task", "team")
            .get(pk=item.id)
        )
        ensure_task_open(item.task)
        if item.status != ITEM_STATUS_PENDING:
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        if action == TEAM_ITEM_ACTION_ASSIGN_LEADER:
            if to_user is None:
                message = "接任负责人时必须指定接收人。"
                raise HandoverError(message)
            if cast("int", to_user.pk) == item.task.subject_user_id:
                raise HandoverError(ACTION_SELF_RECEIVER_MESSAGE)
            _ = TeamMember.objects.update_or_create(
                team=item.team,
                user=to_user,
                defaults={"role": TEAM_MEMBER_ROLE_LEADER, "added_by": actor_id},
            )
        elif action == TEAM_ITEM_ACTION_DEACTIVATE:
            item.team.is_active = False
            item.team.save(update_fields=["is_active", "updated_at"])
        else:
            message = "团队交接动作必须为 assign_leader 或 deactivate。"
            raise HandoverError(message)
        item.action = action
        item.to_user = to_user
        item.status = ITEM_STATUS_DONE
        item.save()
    record_task_event(
        item.task,
        action="handover_team_item_applied",
        actor_id=actor_id,
        extra={
            "team_name": item.team.name,
            "team_action": action,
            "to_user_id": to_user.authentik_user_id if to_user is not None else "",
        },
    )
    return item


def cancel_task(task: HandoverTask, *, actor_id: str) -> HandoverTask:
    with transaction.atomic():
        task = HandoverTask.objects.select_for_update().get(pk=task.id)
        ensure_task_open(task)
        if (
            HandoverAppAction.objects.filter(task=task)
            .filter(
                Q(attempts__gt=0)
                | Q(status__in=(ACTION_STATUS_EXECUTING, ACTION_STATUS_ASYNC_PENDING)),
            )
            .exists()
        ):
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        task.status = TASK_STATUS_CANCELLED
        task.save(update_fields=["status", "updated_at"])
    record_task_event(task, action="handover_task_cancelled", actor_id=actor_id)
    return task



def delete_task(task: HandoverTask, *, actor_id: str) -> None:
    # 单据本身允许清理误建/作废的(仅 cancelled); 删除动作先落审计, 保留可追溯痕迹。
    with transaction.atomic():
        task = HandoverTask.objects.select_for_update().get(pk=task.id)
        if task.status != TASK_STATUS_CANCELLED:
            raise HandoverConflictError(TASK_NOT_DELETABLE_MESSAGE)
        record_task_event(task, action="handover_task_deleted", actor_id=actor_id)
        _ = task.delete()










# ---------------------------------------------------------------------------
# 内部实现
# ---------------------------------------------------------------------------














def _locked_action(action_id: int) -> HandoverAppAction:
    return (
        HandoverAppAction.objects.select_for_update()
        .select_related(
            "app",
            "task",
            "task__subject_user",
            "to_user",
            "execution_to_user",
        )
        .get(pk=action_id)
    )


def _reserve_preview_request(action_id: int) -> _PreviewRequest:
    with transaction.atomic():
        action = _locked_action(action_id)
        ensure_action_status(action, allowed={ACTION_STATUS_PENDING, ACTION_STATUS_PREVIEWED})
        action.preview_generation += 1
        action.save(update_fields=["preview_generation", "updated_at"])
        return _PreviewRequest(
            action_id=action.id,
            generation=action.preview_generation,
            app=action.app,
            hook_url=_handover_hook_url(action.app),
            payload=_hook_payload(action, mode="preview"),
        )


def _record_preview_error(request: _PreviewRequest, error: Exception) -> None:
    with transaction.atomic():
        action = _locked_preview_action(request)
        action.last_error = str(error)
        action.save(update_fields=["last_error", "updated_at"])


def _complete_preview_request(
    request: _PreviewRequest,
    *,
    payload: dict[str, JsonValue],
) -> HandoverAppAction:
    with transaction.atomic():
        action = _locked_preview_action(request)
        ensure_action_status(action, allowed={ACTION_STATUS_PENDING, ACTION_STATUS_PREVIEWED})
        action.preview_payload = payload
        action.status = ACTION_STATUS_PREVIEWED
        action.last_error = ""
        action.save(update_fields=["preview_payload", "status", "last_error", "updated_at"])
        record_task_event(
            action.task,
            action="handover_action_previewed",
            actor_id=LIFECYCLE_ACTOR_ID,
            extra={"app_key": action.app_key_snapshot},
        )
        return action


def _locked_preview_action(request: _PreviewRequest) -> HandoverAppAction:
    action = (
        HandoverAppAction.objects.select_for_update()
        .select_related(
            "app",
            "task",
            "task__subject_user",
            "to_user",
            "execution_to_user",
        )
        .filter(pk=request.action_id, preview_generation=request.generation)
        .first()
    )
    if action is None:
        raise HandoverConflictError(PREVIEW_GENERATION_CONFLICT_MESSAGE)
    return action










def _finish_action_failure(action_id: int, error: Exception) -> None:
    with transaction.atomic():
        action = _locked_action(action_id)
        if action.status != ACTION_STATUS_EXECUTING:
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        action.status = ACTION_STATUS_FAILED
        action.last_error = str(error)
        action.save(update_fields=["status", "last_error", "updated_at"])


def _handover_hook_url(app: App) -> str:
    config = AppWebhookConfig.objects.filter(app=app, enabled=True).first()
    if config is None:
        return ""
    return config.handover_url


def _hook_payload(action: HandoverAppAction, *, mode: str) -> dict[str, JsonValue]:
    task = action.task
    receiver = action.execution_to_user if mode == "execute" else action.to_user
    source_policy = action.execution_policy if mode == "execute" else action.policy
    policy: dict[str, JsonValue] = dict(source_policy)
    if "unowned_strategy" not in policy:
        policy["unowned_strategy"] = "transfer"
    return {
        # task_id 是幂等键: 同一交接单对同一 APP 重复 execute 必须安全。
        "task_id": f"{task.id}:{action.app.app_key}",
        "kind": task.kind,
        "from_user_id": task.subject_user.authentik_user_id,
        "to_user_id": (receiver.authentik_user_id if receiver is not None else None),
        "mode": mode,
        "policy": policy,
    }







































