from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, cast

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AppScope
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.inputs import AuthorizationGroupGrantInput, ScopedDirectGrantInput
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission
from easyauth.grants.services import GrantExpirationInput, GrantMutationInput, GrantService
from easyauth.lifecycle.models import (
    ACTION_FINISHED_STATUSES,
    ACTION_STATUS_ASYNC_PENDING,
    ACTION_STATUS_DONE,
    ACTION_STATUS_EXECUTING,
    ACTION_STATUS_FAILED,
    ACTION_STATUS_PENDING,
    ACTION_STATUS_PREVIEWED,
    ACTION_STATUS_SKIPPED,
    HANDOVER_KIND_OFFBOARD,
    HANDOVER_KIND_TRANSFER,
    ITEM_STATUS_DONE,
    ITEM_STATUS_PENDING,
    ITEM_STATUS_SKIPPED,
    TASK_OPEN_STATUSES,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_IN_PROGRESS,
    TEAM_ITEM_ACTION_ASSIGN_LEADER,
    TEAM_ITEM_ACTION_DEACTIVATE,
    HandoverAppAction,
    HandoverGrantItem,
    HandoverTask,
    HandoverTeamItem,
    OnboardingTemplate,
    OnboardingTemplateItem,
    TransferPlan,
)
from easyauth.outbox.services import enqueue_task
from easyauth.teams.models import TEAM_MEMBER_ROLE_LEADER, TeamMember
from easyauth.webhooks.hooks import HookCallError, HookResponse, signed_hook_get, signed_hook_post
from easyauth.webhooks.models import AppWebhookConfig

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.applications.ops_models import JsonValue

LIFECYCLE_ACTOR_ID: Final = "lifecycle"
DISABLE_ACCOUNT_TASK_NAME: Final = "easyauth.lifecycle.disable_departed_account"
HOOK_EVENT_PREVIEW: Final = "lifecycle.handover.preview"
HOOK_EVENT_EXECUTE: Final = "lifecycle.handover.execute"
ASYNC_POLL_MAX_ATTEMPTS: Final = 10

TASK_ALREADY_OPEN_MESSAGE: Final = "该人员已有进行中的交接单。"
TASK_NOT_OPEN_MESSAGE: Final = "交接单不在进行中状态。"
ACTION_RECEIVER_XOR_MESSAGE: Final = "接收人与释放公海策略必须严格二选一。"
ACTION_SELF_RECEIVER_MESSAGE: Final = "接收人不能是交接当事人本人。"
ACTION_RECEIVER_FROZEN_MESSAGE: Final = "交接已开始执行, 不允许更换接收人或释放策略。"
ACTION_NOT_OPERABLE_MESSAGE: Final = "该应用交接动作当前状态不允许执行此操作。"
TASK_KIND_CONFLICT_MESSAGE: Final = "该人员已有其他类型的进行中交接单。"
TRANSFER_CONFIRMATION_CONFLICT_MESSAGE: Final = "转岗差异已使用其他选择完成确认。"
TRANSFER_PLAN_STALE_MESSAGE: Final = "授权已在差异生成后发生变化, 请重新生成差异。"
TRANSFER_TASK_REQUIRED_MESSAGE: Final = "只有转岗单可以处理权限差异。"
ASYNC_STATUS_URL_REQUIRED_MESSAGE: Final = "异步交接缺少状态查询 URL。"
ASYNC_POLL_LIMIT_MESSAGE: Final = "异步交接状态查询已达到重试上限。"
ASYNC_ACCEPTED_LOCATION_REQUIRED_MESSAGE: Final = (
    "应用交接状态接口返回 202 时必须提供状态查询 URL。"
)
EXECUTE_ACCEPTED_LOCATION_REQUIRED_MESSAGE: Final = "应用交接接口返回 202 时必须提供状态查询 URL。"
PREVIEW_SYNC_REQUIRED_MESSAGE: Final = "应用交接预览接口必须同步返回 HTTP 200。"
TEMPLATE_TERM_INVALID_MESSAGE: Final = "模板项期限配置无效。"
CATALOG_TARGET_DELETED_MESSAGE: Final = "授权目录项已删除, 无法执行交接。"
HOOK_NOT_DECLARED_RESULT: Final = "skipped"


class HandoverError(RuntimeError):
    pass


class HandoverConflictError(HandoverError):
    pass


@dataclass(frozen=True, slots=True)
class OffboardingStartResult:
    task: HandoverTask
    created: bool
    removed_membership_count: int


LOCAL_ADMIN_LIFECYCLE_MESSAGE: Final = "系统内置管理员不参与离职/转岗交接。"


def _assert_lifecycle_subject(subject: UserMirror) -> None:
    # break-glass 本地管理员不是员工, 禁止对其建离职/转岗交接单(误操作会禁掉救援入口)。
    if subject.authentik_user_id.startswith(LOCAL_ADMIN_SUBJECT_PREFIX):
        raise HandoverConflictError(LOCAL_ADMIN_LIFECYCLE_MESSAGE)


def ensure_handover_task(
    *,
    subject: UserMirror,
    kind: str,
    created_by: str,
    reason: str = "",
    snapshot_grant_ids: tuple[int, ...] | None = None,
) -> tuple[HandoverTask, bool]:
    """建单(幂等): 同一当事人已有进行中交接单时直接返回既有单。"""
    _assert_lifecycle_subject(subject)
    with transaction.atomic():
        subject = UserMirror.objects.select_for_update().get(pk=subject.id)
        existing = (
            HandoverTask.objects.select_for_update()
            .filter(subject_user=subject, status__in=TASK_OPEN_STATUSES)
            .first()
        )
        if existing is not None:
            if existing.kind != kind:
                raise HandoverConflictError(TASK_KIND_CONFLICT_MESSAGE)
            return existing, False
        snapshot_grants = _snapshot_grants(
            subject=subject,
            explicit_grant_ids=snapshot_grant_ids,
        )
        task = HandoverTask.objects.create(
            kind=kind,
            subject_user=subject,
            created_by=created_by,
            reason=reason,
        )
        _snapshot_grant_items(task, grants=snapshot_grants)
        _snapshot_app_actions(task, grants=snapshot_grants)
        _snapshot_leader_teams(task)
        if kind == HANDOVER_KIND_TRANSFER:
            _ = TransferPlan.objects.create(task=task)
        _record_task_event(task, action="handover_task_created", actor_id=created_by)
        return refresh_task_status(task), True


def start_offboarding(
    subject: UserMirror,
    *,
    created_by: str = "directory_sync",
    snapshot_grant_ids: tuple[int, ...] | None = None,
) -> OffboardingStartResult:
    """离职立即项(§2.2 铁律一): 建单 + 禁号入列 + 移出所有团队; 数据交接进入缓冲。

    调用方须保证授权撤销已由既有离职回收完成(apply_directory_status)。
    """
    with transaction.atomic():
        task, created = ensure_handover_task(
            subject=subject,
            kind=HANDOVER_KIND_OFFBOARD,
            created_by=created_by,
            reason="目录同步检出离职" if created_by == "directory_sync" else "",
            snapshot_grant_ids=snapshot_grant_ids,
        )
        removed = _remove_team_memberships(subject, task)
        _schedule_account_disable(subject, task=task)
    return OffboardingStartResult(
        task=task,
        created=created,
        removed_membership_count=removed,
    )


def update_action_receiver(
    *,
    action: HandoverAppAction,
    to_user: UserMirror | None,
    policy: dict[str, JsonValue],
) -> HandoverAppAction:
    with transaction.atomic():
        locked = _locked_action(action.id)
        _ensure_task_open(locked.task)
        _validate_receiver_strategy(locked, to_user=to_user, policy=policy)
        has_processed_items = (
            HandoverGrantItem.objects.filter(
                task=locked.task,
                app=locked.app,
            )
            .exclude(status=ITEM_STATUS_PENDING)
            .exists()
        )
        if locked.attempts or has_processed_items:
            if locked.to_user_id != (to_user.id if to_user is not None else None) or (
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
    # preview 必须持锁到响应落库, 避免旧接收人的响应覆盖并发换人/skip。
    with transaction.atomic():
        action = _locked_action(action.id)
        _ensure_action_status(action, allowed={ACTION_STATUS_PENDING, ACTION_STATUS_PREVIEWED})
        hook_url = _handover_hook_url(action.app)
        if not hook_url:
            action.preview_payload = {"assets": [], "hook": HOOK_NOT_DECLARED_RESULT}
        else:
            try:
                response = signed_hook_post(
                    app=action.app,
                    url=hook_url,
                    event_type=HOOK_EVENT_PREVIEW,
                    delivery_id=uuid.uuid4().hex,
                    payload=_hook_payload(action, mode="preview"),
                )
                action.preview_payload = _preview_response_payload(response)
            except HookCallError as error:
                action.last_error = str(error)
                action.save(update_fields=["last_error", "updated_at"])
                raise
        action.status = ACTION_STATUS_PREVIEWED
        action.last_error = ""
        action.save(update_fields=["preview_payload", "status", "last_error", "updated_at"])
        _record_task_event(
            action.task,
            action="handover_action_previewed",
            actor_id=LIFECYCLE_ACTOR_ID,
            extra={"app_key": action.app_key_snapshot},
        )
        return action


def execute_action(action: HandoverAppAction) -> HandoverAppAction:
    """执行单个 APP 的交接: 转授勾选权限(EasyAuth 内部) + 调 APP 钩子交接数据。

    幂等以 task_id 为键(APP 侧承诺重复 execute 安全); 失败置 failed 可重试,
    单 APP 失败不影响其他 APP。
    """
    with transaction.atomic():
        action = _locked_action(action.id)
        _ensure_action_status(
            action,
            allowed={ACTION_STATUS_PENDING, ACTION_STATUS_PREVIEWED, ACTION_STATUS_FAILED},
        )
        _validate_receiver_strategy(action, to_user=action.to_user, policy=action.policy)
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
        transferred = _transfer_selected_grants(action)
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
                _record_task_event(
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
        _record_task_event(
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
    _record_task_event(
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
        _ensure_action_status(action, allowed={ACTION_STATUS_ASYNC_PENDING})
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
    _record_task_event(
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
        _ensure_action_status(
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
    _record_task_event(
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
        _ensure_task_open(item.task)
        if item.status != ITEM_STATUS_PENDING:
            raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)
        if action == TEAM_ITEM_ACTION_ASSIGN_LEADER:
            if to_user is None:
                message = "接任负责人时必须指定接收人。"
                raise HandoverError(message)
            if to_user.id == item.task.subject_user_id:
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
    _record_task_event(
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
        _ensure_task_open(task)
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
    _record_task_event(task, action="handover_task_cancelled", actor_id=actor_id)
    return task


TASK_NOT_DELETABLE_MESSAGE: Final = (
    "只有已取消的交接单可以删除; 进行中的请先取消, 已完成的作为交接史料保留。"
)


def delete_task(task: HandoverTask, *, actor_id: str) -> None:
    # 单据本身允许清理误建/作废的(仅 cancelled); 删除动作先落审计, 保留可追溯痕迹。
    with transaction.atomic():
        task = HandoverTask.objects.select_for_update().get(pk=task.id)
        if task.status != TASK_STATUS_CANCELLED:
            raise HandoverConflictError(TASK_NOT_DELETABLE_MESSAGE)
        _record_task_event(task, action="handover_task_deleted", actor_id=actor_id)
        _ = task.delete()


def refresh_task_status(task: HandoverTask) -> HandoverTask:
    # 所有 APP 均 done/skipped 且团队项处理完 → 交接单完成; 有任何进展 → in_progress。
    with transaction.atomic():
        task = HandoverTask.objects.select_for_update().get(pk=task.id)
        if task.status not in TASK_OPEN_STATUSES:
            return task
        actions = list(HandoverAppAction.objects.filter(task=task))
        team_items = list(HandoverTeamItem.objects.filter(task=task))
        plan_confirmed = True
        if task.kind == HANDOVER_KIND_TRANSFER:
            plan = TransferPlan.objects.filter(task=task).first()
            plan_confirmed = plan is not None and plan.confirmed_at is not None
        actions_finished = all(a.status in ACTION_FINISHED_STATUSES for a in actions)
        teams_finished = all(item.status != ITEM_STATUS_PENDING for item in team_items)
        if actions_finished and teams_finished and plan_confirmed:
            task.status = TASK_STATUS_COMPLETED
            task.save(update_fields=["status", "updated_at"])
            _record_task_event(task, action="handover_task_completed", actor_id=LIFECYCLE_ACTOR_ID)
            if task.kind == HANDOVER_KIND_TRANSFER:
                # 模型约定"转岗单确认后清除"部门变更提示: 转岗单完成即代表人事已处理该线索。
                _ = UserMirror.objects.filter(
                    pk=task.subject_user_id,
                    department_changed_at__isnull=False,
                ).update(department_changed_at=None)
            return task
        started = any(a.status != ACTION_STATUS_PENDING for a in actions) or any(
            item.status != ITEM_STATUS_PENDING for item in team_items
        )
        if started and task.status != TASK_STATUS_IN_PROGRESS:
            task.status = TASK_STATUS_IN_PROGRESS
            task.save(update_fields=["status", "updated_at"])
        return task


def build_transfer_grant_diff(
    *,
    task: HandoverTask,
    template: OnboardingTemplate,
) -> TransferPlan:
    """转岗权限差异(§7 决策 9): 撤销不在新模板内的授权 + 补齐新模板, 确认时逐条可勾选。"""
    with transaction.atomic():
        task = HandoverTask.objects.select_for_update().get(pk=task.id)
        _ensure_transfer_task_open(task)
        plan = TransferPlan.objects.select_for_update().get(task=task)
        if plan.confirmed_at is not None:
            raise HandoverConflictError(TRANSFER_CONFIRMATION_CONFLICT_MESSAGE)
        current_entries = {
            _grant_item_key(item): item for item in HandoverGrantItem.objects.filter(task=task)
        }
        current_keys = set(current_entries)
        template_entries = {
            _template_item_key(item): item
            for item in OnboardingTemplateItem.objects.select_related(
                "app",
                "authorization_group",
                "permission",
            ).filter(template=template)
        }
        common = current_keys & set(template_entries)
        term_changes = {
            key
            for key in common
            if _template_term_replaces_snapshot(
                template_entries[key],
                current_entries[key],
            )
        }
        revoke = sorted(current_keys - set(template_entries))
        add = sorted((set(template_entries) - current_keys) | term_changes)
        keep = sorted(common - term_changes)
        plan.new_template = template
        plan.grant_diff = {
            "revoke": [_diff_entry(key) for key in revoke],
            "add": [_diff_entry(key) for key in add],
            "keep": [_diff_entry(key) for key in keep],
        }
        plan.save(update_fields=["new_template", "grant_diff", "updated_at"])
        return plan


def confirm_transfer_grant_diff(
    *,
    task: HandoverTask,
    revoke_keys: list[str],
    add_keys: list[str],
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
            TransferPlan.objects.select_for_update().select_related("new_template").get(task=task)
        )
        if plan.confirmed_at is not None:
            if (
                plan.confirmed_revoke_keys == canonical_revoke
                and plan.confirmed_add_keys == canonical_add
            ):
                return plan
            raise HandoverConflictError(TRANSFER_CONFIRMATION_CONFLICT_MESSAGE)
        _ensure_task_open(task)
        if plan.new_template is None:
            message = "请先选择新岗位模板并生成差异清单。"
            raise HandoverError(message)
        diff = plan.grant_diff
        allowed_revoke = {_entry_key(entry) for entry in _diff_list(diff, "revoke")}
        allowed_add = {_entry_key(entry) for entry in _diff_list(diff, "add")}
        unknown = (set(canonical_revoke) - allowed_revoke) | (set(canonical_add) - allowed_add)
        if unknown:
            message = f"差异项不存在: {sorted(unknown)[0]}。"
            raise HandoverError(message)
        revoke_set = set(canonical_revoke)
        add_set = set(canonical_add)
        template_items = {
            _template_item_key(item): item
            for item in OnboardingTemplateItem.objects.select_related(
                "app",
                "authorization_group",
                "permission",
            ).filter(template=plan.new_template)
        }
        if add_set - template_items.keys():
            raise HandoverConflictError(TRANSFER_PLAN_STALE_MESSAGE)
        apps = {key.split(":", 1)[0] for key in revoke_set | add_set}
        _lock_and_validate_transfer_grant_versions(task=task, app_keys=apps)
        for app_key in sorted(apps):
            _apply_transfer_diff_for_app(
                subject=task.subject_user,
                app_key=app_key,
                revoke_keys={key for key in revoke_set if key.startswith(f"{app_key}:")},
                add_items=[
                    item
                    for key, item in template_items.items()
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
        _record_task_event(
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


def onboard_user(
    *,
    user: UserMirror,
    template: OnboardingTemplate,
    actor_id: str,
) -> list[AccessGrant]:
    """一键入职: 按模板项批量创建授权(每 APP 一条 current 授权, 复用现有授权服务)。"""
    with transaction.atomic():
        user = UserMirror.objects.select_for_update().get(pk=user.id)
        template = OnboardingTemplate.objects.select_for_update().get(pk=template.id)
        grants: list[AccessGrant] = []
        items = list(
            OnboardingTemplateItem.objects.select_related(
                "app",
                "authorization_group",
                "permission",
            ).filter(template=template, app__is_active=True),
        )
        by_app: dict[int, list[OnboardingTemplateItem]] = {}
        for item in items:
            by_app.setdefault(item.app_id, []).append(item)
        _ = list(
            AccessGrant.objects.select_for_update().filter(
                user=user,
                app_id__in=by_app,
                is_current=True,
            ),
        )
        for app_items in by_app.values():
            app = app_items[0].app
            grants.append(
                _merge_into_current_grant(
                    user=user,
                    app=app,
                    groups=[
                        AuthorizationGroupGrantInput(
                            authorization_group=i.authorization_group,
                            expires_at=_template_item_expiry(i),
                        )
                        for i in app_items
                        if i.authorization_group is not None
                    ],
                    direct_grants=[
                        ScopedDirectGrantInput(
                            permission=i.permission,
                            scope_key=i.scope_key,
                            expires_at=_template_item_expiry(i),
                        )
                        for i in app_items
                        if i.permission is not None
                    ],
                    actor_id=actor_id,
                ),
            )
        _ = AuditService.record(
            AuditRecord(
                actor_type="admin",
                actor_id=actor_id,
                action="lifecycle_onboarded",
                target_type="user",
                target_id=user.authentik_user_id,
                metadata={
                    "template": template.name,
                    "app_count": len(by_app),
                },
            ),
        )
        return grants


# ---------------------------------------------------------------------------
# 内部实现
# ---------------------------------------------------------------------------


def _snapshot_grant_items(task: HandoverTask, *, grants: list[AccessGrant]) -> None:
    now = timezone.now()
    for grant in grants:
        group_links = (
            AccessGrantGroup.objects.select_related("authorization_group")
            .filter(grant=grant, authorization_group__is_active=True)
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        )
        for link in group_links:
            _ = HandoverGrantItem.objects.create(
                task=task,
                app=grant.app,
                app_key_snapshot=grant.app.app_key,
                app_name_snapshot=grant.app.name,
                app_catalog_version_snapshot=grant.app.catalog_version,
                authorization_group=link.authorization_group,
                target_kind_snapshot="group",
                target_key_snapshot=link.authorization_group.key,
                target_name_snapshot=link.authorization_group.name,
                source_grant_id=grant.id,
                source_grant_version=grant.version,
                grant_type="permanent" if link.expires_at is None else "timed",
                grant_expires_at=link.expires_at,
            )
        permission_links = (
            AccessGrantPermission.objects.select_related("permission")
            .filter(
                grant=grant,
                permission__is_active=True,
                permission__deprecated_at__isnull=True,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        )
        active_scopes = set(
            AppScope.objects.filter(app=grant.app, is_active=True).values_list("key", flat=True),
        )
        for permission_link in permission_links:
            if permission_link.scope_key not in active_scopes:
                continue
            _ = HandoverGrantItem.objects.create(
                task=task,
                app=grant.app,
                app_key_snapshot=grant.app.app_key,
                app_name_snapshot=grant.app.name,
                app_catalog_version_snapshot=grant.app.catalog_version,
                permission=permission_link.permission,
                scope_key=permission_link.scope_key,
                target_kind_snapshot="permission",
                target_key_snapshot=permission_link.permission.key,
                target_name_snapshot=permission_link.permission.name,
                source_grant_id=grant.id,
                source_grant_version=grant.version,
                grant_type="permanent" if permission_link.expires_at is None else "timed",
                grant_expires_at=permission_link.expires_at,
            )


def _snapshot_app_actions(task: HandoverTask, *, grants: list[AccessGrant]) -> None:
    # 交接面 = 当事人有授权痕迹的 APP, 加上声明了交接钩子的 APP。
    app_ids = {grant.app_id for grant in grants}
    hook_app_ids = set(
        AppWebhookConfig.objects.filter(enabled=True, app__is_active=True)
        .exclude(handover_url="")
        .values_list("app_id", flat=True),
    )
    for app in App.objects.filter(id__in=app_ids | hook_app_ids):
        _ = HandoverAppAction.objects.create(
            task=task,
            app=app,
            app_key_snapshot=app.app_key,
            app_name_snapshot=app.name,
            app_catalog_version_snapshot=app.catalog_version,
        )


def _snapshot_grants(
    *,
    subject: UserMirror,
    explicit_grant_ids: tuple[int, ...] | None,
) -> list[AccessGrant]:
    queryset = AccessGrant.objects.select_related("app").filter(
        user=subject,
        app__is_active=True,
    )
    if explicit_grant_ids is not None:
        grants_by_id = {grant.id: grant for grant in queryset.filter(id__in=explicit_grant_ids)}
        missing = set(explicit_grant_ids) - grants_by_id.keys()
        if missing:
            message = f"授权快照不存在: {min(missing)}。"
            raise HandoverError(message)
        return [grants_by_id[grant_id] for grant_id in explicit_grant_ids]
    now = timezone.now()
    return list(
        queryset.filter(is_current=True, status="active")
        .filter(
            Q(grant_groups__expires_at__isnull=True)
            | Q(grant_groups__expires_at__gt=now)
            | Q(grant_permissions__expires_at__isnull=True)
            | Q(grant_permissions__expires_at__gt=now),
        )
        .distinct(),
    )


def _snapshot_leader_teams(task: HandoverTask) -> None:
    led_teams = TeamMember.objects.select_related("team").filter(
        user=task.subject_user,
        role=TEAM_MEMBER_ROLE_LEADER,
        team__is_active=True,
    )
    for membership in led_teams:
        _ = HandoverTeamItem.objects.create(task=task, team=membership.team)


def _remove_team_memberships(subject: UserMirror, task: HandoverTask) -> int:
    removed, _detail = TeamMember.objects.filter(user=subject).delete()
    if removed:
        _record_task_event(
            task,
            action="handover_memberships_removed",
            actor_id=LIFECYCLE_ACTOR_ID,
            extra={"removed_count": removed},
        )
    return removed


def _schedule_account_disable(subject: UserMirror, *, task: HandoverTask) -> None:
    # Authentik 禁号/吊销会话走 Celery(可重试), 不阻塞目录同步事务。
    user_pk = subject.id
    _ = enqueue_task(
        event_key=f"lifecycle-disable-account:{task.id}",
        task_name=DISABLE_ACCOUNT_TASK_NAME,
        args=[user_pk],
    )


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


def _ensure_task_open(task: HandoverTask) -> None:
    if task.status not in TASK_OPEN_STATUSES:
        raise HandoverConflictError(TASK_NOT_OPEN_MESSAGE)


def _ensure_transfer_task_open(task: HandoverTask) -> None:
    _ensure_task_open(task)
    if task.kind != HANDOVER_KIND_TRANSFER:
        raise HandoverConflictError(TRANSFER_TASK_REQUIRED_MESSAGE)


def _ensure_action_status(action: HandoverAppAction, *, allowed: set[str]) -> None:
    _ensure_task_open(action.task)
    if action.status not in allowed:
        raise HandoverConflictError(ACTION_NOT_OPERABLE_MESSAGE)


def _validate_receiver_strategy(
    action: HandoverAppAction,
    *,
    to_user: UserMirror | None,
    policy: dict[str, JsonValue],
) -> None:
    releases_to_pool = policy.get("unowned_strategy") == "release_to_pool"
    if (to_user is not None) == releases_to_pool:
        raise HandoverError(ACTION_RECEIVER_XOR_MESSAGE)
    if to_user is not None and to_user.id == action.task.subject_user_id:
        raise HandoverError(ACTION_SELF_RECEIVER_MESSAGE)


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


def _transfer_selected_grants(action: HandoverAppAction) -> int:
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
    _ = _merge_into_current_grant(
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


def _merge_into_current_grant(
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
                    else _later_expiry(link.expires_at, incoming.expires_at)
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
                    else _later_expiry(permission_link.expires_at, incoming.expires_at)
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


def _apply_transfer_diff_for_app(
    *,
    subject: UserMirror,
    app_key: str,
    revoke_keys: set[str],
    add_items: list[OnboardingTemplateItem],
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
        _collect_kept_targets(
            existing=existing,
            app_key=app_key,
            revoke_keys=revoke_keys,
            groups=groups,
            direct=direct,
        )
    for item in add_items:
        item_expiry = _template_item_expiry(item)
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


def _lock_and_validate_transfer_grant_versions(
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
    for row in snapshot_versions:
        app_key = cast("str", row[0])
        version = cast("int", row[1])
        expected_by_app.setdefault(app_key, set()).add(version)
    for app_key, expected_versions in expected_by_app.items():
        current = current_by_app.get(app_key)
        if (
            len(expected_versions) != 1
            or current is None
            or current.version not in expected_versions
        ):
            raise HandoverConflictError(TRANSFER_PLAN_STALE_MESSAGE)


def _collect_kept_targets(
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


def _grant_item_key(item: HandoverGrantItem) -> str:
    base = f"{item.app_key_snapshot}:{item.target_kind_snapshot}:{item.target_key_snapshot}"
    if item.target_kind_snapshot == "group":
        return base
    return f"{base}:{item.scope_key}"


def _template_item_key(item: OnboardingTemplateItem) -> str:
    if item.authorization_group is not None:
        return f"{item.app.app_key}:group:{item.authorization_group.key}"
    permission = item.permission
    permission_key = permission.key if permission is not None else ""
    return f"{item.app.app_key}:permission:{permission_key}:{item.scope_key}"


def _diff_entry(key: str) -> dict[str, JsonValue]:
    return {"key": key, "selected": True}


def _diff_list(diff: dict[str, JsonValue], name: str) -> list[dict[str, JsonValue]]:
    value = diff.get(name)
    if not isinstance(value, list):
        return []
    return [element for element in value if isinstance(element, dict)]


def _entry_key(entry: dict[str, JsonValue]) -> str:
    key = entry.get("key")
    return key if isinstance(key, str) else ""


def _template_item_expiry(item: OnboardingTemplateItem) -> datetime | None:
    if item.grant_type == "permanent":
        return None
    if item.grant_type != "timed" or item.duration_days is None:
        raise HandoverError(TEMPLATE_TERM_INVALID_MESSAGE)
    return timezone.now() + timedelta(days=item.duration_days)


def _template_term_replaces_snapshot(
    template_item: OnboardingTemplateItem,
    snapshot_item: HandoverGrantItem,
) -> bool:
    if template_item.grant_type == "permanent":
        return snapshot_item.grant_expires_at is not None
    return True


def _later_expiry(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None or right is None:
        return None
    return max(left, right)


def _record_task_event(
    task: HandoverTask,
    *,
    action: str,
    actor_id: str,
    extra: dict[str, JsonValue] | None = None,
) -> None:
    metadata: dict[str, JsonValue] = {
        "kind": task.kind,
        "subject_user_id": task.subject_user.authentik_user_id,
        "status": task.status,
    }
    if extra:
        metadata.update(extra)
    _ = AuditService.record(
        AuditRecord(
            actor_type="system" if actor_id in {LIFECYCLE_ACTOR_ID, "directory_sync"} else "admin",
            actor_id=actor_id,
            action=action,
            target_type="handover_task",
            target_id=str(task.id),
            metadata=metadata,
        ),
    )
