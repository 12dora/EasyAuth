from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, cast

from celery import current_app
from django.db import transaction
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AuthorizationGroup
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.inputs import ScopedDirectGrantInput
from easyauth.grants.models import (
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from easyauth.grants.services import GrantMutationInput, GrantService
from easyauth.lifecycle.models import (
    ACTION_FINISHED_STATUSES,
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
from easyauth.teams.models import TEAM_MEMBER_ROLE_LEADER, TeamMember
from easyauth.webhooks.hooks import HookCallError, signed_hook_post
from easyauth.webhooks.models import AppWebhookConfig

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.accounts.models import UserMirror
    from easyauth.applications.ops_models import JsonValue
    from easyauth.grants.services import GrantType

LIFECYCLE_ACTOR_ID: Final = "lifecycle"
DISABLE_ACCOUNT_TASK_NAME: Final = "easyauth.lifecycle.disable_departed_account"
HOOK_EVENT_PREVIEW: Final = "lifecycle.handover.preview"
HOOK_EVENT_EXECUTE: Final = "lifecycle.handover.execute"

TASK_ALREADY_OPEN_MESSAGE: Final = "该人员已有进行中的交接单。"
TASK_NOT_OPEN_MESSAGE: Final = "交接单不在进行中状态。"
ACTION_RECEIVER_REQUIRED_MESSAGE: Final = "该应用尚未指定接收人, 也未选择释放策略。"
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


def ensure_handover_task(
    *,
    subject: UserMirror,
    kind: str,
    created_by: str,
    reason: str = "",
) -> tuple[HandoverTask, bool]:
    """建单(幂等): 同一当事人已有进行中交接单时直接返回既有单。"""
    with transaction.atomic():
        existing = (
            HandoverTask.objects.select_for_update()
            .filter(subject_user=subject, status__in=TASK_OPEN_STATUSES)
            .first()
        )
        if existing is not None:
            return existing, False
        task = HandoverTask.objects.create(
            kind=kind,
            subject_user=subject,
            created_by=created_by,
            reason=reason,
        )
        _snapshot_grant_items(task)
        _snapshot_app_actions(task)
        _snapshot_leader_teams(task)
        if kind == HANDOVER_KIND_TRANSFER:
            _ = TransferPlan.objects.create(task=task)
        _record_task_event(task, action="handover_task_created", actor_id=created_by)
        return task, True


def start_offboarding(subject: UserMirror, *, created_by: str = "directory_sync") -> (
    OffboardingStartResult
):
    """离职立即项(§2.2 铁律一): 建单 + 禁号入列 + 移出所有团队; 数据交接进入缓冲。

    调用方须保证授权撤销已由既有离职回收完成(apply_directory_status)。
    """
    task, created = ensure_handover_task(
        subject=subject,
        kind=HANDOVER_KIND_OFFBOARD,
        created_by=created_by,
        reason="目录同步检出离职" if created_by == "directory_sync" else "",
    )
    removed = _remove_team_memberships(subject, task)
    _schedule_account_disable(subject)
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
    if action.task.status not in TASK_OPEN_STATUSES:
        raise HandoverConflictError(TASK_NOT_OPEN_MESSAGE)
    action.to_user = to_user
    action.policy = policy
    if action.status in {ACTION_STATUS_FAILED, ACTION_STATUS_PREVIEWED}:
        # 改接收人后旧预览/失败状态作废, 回到待交接。
        action.status = ACTION_STATUS_PENDING
        action.preview_payload = {}
        action.last_error = ""
    action.save()
    return action


def preview_action(action: HandoverAppAction) -> HandoverAppAction:
    """调 APP 钩子 preview(不落库业务数据), 只报影响面。"""
    _ensure_action_operable(action)
    hook_url = _handover_hook_url(action.app)
    if not hook_url:
        action.preview_payload = {"assets": [], "hook": HOOK_NOT_DECLARED_RESULT}
        action.status = ACTION_STATUS_PREVIEWED
        action.save(update_fields=["preview_payload", "status", "updated_at"])
        return action
    try:
        response = signed_hook_post(
            app=action.app,
            url=hook_url,
            event_type=HOOK_EVENT_PREVIEW,
            delivery_id=uuid.uuid4().hex,
            payload=_hook_payload(action, mode="preview"),
        )
    except HookCallError as error:
        action.last_error = str(error)
        action.save(update_fields=["last_error", "updated_at"])
        raise
    action.preview_payload = response
    action.status = ACTION_STATUS_PREVIEWED
    action.last_error = ""
    action.save(update_fields=["preview_payload", "status", "last_error", "updated_at"])
    _record_task_event(
        action.task,
        action="handover_action_previewed",
        actor_id=LIFECYCLE_ACTOR_ID,
        extra={"app_key": action.app.app_key},
    )
    return action


def execute_action(action: HandoverAppAction) -> HandoverAppAction:
    """执行单个 APP 的交接: 转授勾选权限(EasyAuth 内部) + 调 APP 钩子交接数据。

    幂等以 task_id 为键(APP 侧承诺重复 execute 安全); 失败置 failed 可重试,
    单 APP 失败不影响其他 APP。
    """
    _ensure_action_operable(action)
    if action.to_user is None and not _releases_to_pool(action):
        raise HandoverError(ACTION_RECEIVER_REQUIRED_MESSAGE)
    action.status = ACTION_STATUS_EXECUTING
    action.attempts += 1
    action.save(update_fields=["status", "attempts", "updated_at"])

    try:
        transferred = _transfer_selected_grants(action)
        hook_url = _handover_hook_url(action.app)
        if hook_url:
            result = signed_hook_post(
                app=action.app,
                url=hook_url,
                event_type=HOOK_EVENT_EXECUTE,
                delivery_id=uuid.uuid4().hex,
                payload=_hook_payload(action, mode="execute"),
            )
        else:
            result = _hook_skipped_result()
    except (HookCallError, HandoverError) as error:
        action.status = ACTION_STATUS_FAILED
        action.last_error = str(error)
        action.save(update_fields=["status", "last_error", "updated_at"])
        _record_task_event(
            action.task,
            action="handover_action_failed",
            actor_id=LIFECYCLE_ACTOR_ID,
            extra={"app_key": action.app.app_key, "error": str(error)},
        )
        raise

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
                action.to_user.authentik_user_id if action.to_user is not None else ""
            ),
        },
    )
    _ = refresh_task_status(action.task)
    return action


def _hook_skipped_result() -> dict[str, JsonValue]:
    return {"hook": HOOK_NOT_DECLARED_RESULT}


def skip_action(action: HandoverAppAction, *, actor_id: str) -> HandoverAppAction:
    _ensure_action_operable(action)
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
    if item.task.status not in TASK_OPEN_STATUSES:
        raise HandoverConflictError(TASK_NOT_OPEN_MESSAGE)
    with transaction.atomic():
        if action == TEAM_ITEM_ACTION_ASSIGN_LEADER:
            if to_user is None:
                message = "接任负责人时必须指定接收人。"
                raise HandoverError(message)
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
    if task.status not in TASK_OPEN_STATUSES:
        raise HandoverConflictError(TASK_NOT_OPEN_MESSAGE)
    task.status = TASK_STATUS_CANCELLED
    task.save(update_fields=["status", "updated_at"])
    _record_task_event(task, action="handover_task_cancelled", actor_id=actor_id)
    return task


def refresh_task_status(task: HandoverTask) -> HandoverTask:
    # 所有 APP 均 done/skipped 且团队项处理完 → 交接单完成; 有任何进展 → in_progress。
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
    if actions and actions_finished and teams_finished and plan_confirmed:
        task.status = TASK_STATUS_COMPLETED
        task.save(update_fields=["status", "updated_at"])
        _record_task_event(task, action="handover_task_completed", actor_id=LIFECYCLE_ACTOR_ID)
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
    plan = TransferPlan.objects.get(task=task)
    current_keys = {
        _grant_item_key(item)
        for item in HandoverGrantItem.objects.select_related(
            "app",
            "authorization_group",
            "permission",
        ).filter(task=task)
    }
    template_entries = {
        _template_item_key(item): item
        for item in OnboardingTemplateItem.objects.select_related(
            "app",
            "authorization_group",
            "permission",
        ).filter(template=template)
    }
    revoke = sorted(current_keys - set(template_entries))
    add = sorted(set(template_entries) - current_keys)
    keep = sorted(current_keys & set(template_entries))
    plan.new_template = template
    plan.grant_diff = {
        "revoke": [_diff_entry(key) for key in revoke],
        "add": [_diff_entry(key) for key in add],
        "keep": [_diff_entry(key) for key in keep],
    }
    plan.confirmed_at = None
    plan.save()
    return plan


def confirm_transfer_grant_diff(
    *,
    task: HandoverTask,
    revoke_keys: list[str],
    add_keys: list[str],
    actor_id: str,
) -> TransferPlan:
    """按管理员勾选执行转岗权限调整(EasyAuth 内部完成, 无需钩子)。"""
    plan = TransferPlan.objects.select_related("new_template").get(task=task)
    if plan.new_template is None:
        message = "请先选择新岗位模板并生成差异清单。"
        raise HandoverError(message)
    subject = task.subject_user
    diff = plan.grant_diff
    allowed_revoke = {_entry_key(entry) for entry in _diff_list(diff, "revoke")}
    allowed_add = {_entry_key(entry) for entry in _diff_list(diff, "add")}
    revoke_set = {key for key in revoke_keys if key in allowed_revoke}
    add_set = {key for key in add_keys if key in allowed_add}
    template_items = {
        _template_item_key(item): item
        for item in OnboardingTemplateItem.objects.select_related(
            "app",
            "authorization_group",
            "permission",
        ).filter(template=plan.new_template)
    }
    apps = {key.split(":", 1)[0] for key in revoke_set | add_set}
    for app_key in sorted(apps):
        _apply_transfer_diff_for_app(
            subject=subject,
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
    plan.save(update_fields=["confirmed_at", "updated_at"])
    _record_task_event(
        task,
        action="handover_grant_diff_confirmed",
        actor_id=actor_id,
        extra={
            "revoked": cast("JsonValue", sorted(revoke_set)),
            "added": cast("JsonValue", sorted(add_set)),
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
    for app_items in by_app.values():
        app = app_items[0].app
        grants.append(
            _merge_into_current_grant(
                user=user,
                app=app,
                groups=[i.authorization_group for i in app_items if i.authorization_group],
                direct_grants=[
                    ScopedDirectGrantInput(permission=i.permission, scope_key=i.scope_key)
                    for i in app_items
                    if i.permission is not None
                ],
                grant_type=_merged_grant_type(app_items),
                grant_expires_at=_merged_expiry(app_items),
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


def _snapshot_grant_items(task: HandoverTask) -> None:
    for grant in _latest_grants_per_app(task.subject_user):
        group_links = AccessGrantGroup.objects.select_related("authorization_group").filter(
            grant=grant,
        )
        for link in group_links:
            _ = HandoverGrantItem.objects.create(
                task=task,
                app=grant.app,
                authorization_group=link.authorization_group,
                grant_type=grant.grant_type,
                grant_expires_at=grant.grant_expires_at,
            )
        permission_links = AccessGrantPermission.objects.select_related("permission").filter(
            grant=grant,
        )
        for permission_link in permission_links:
            _ = HandoverGrantItem.objects.create(
                task=task,
                app=grant.app,
                permission=permission_link.permission,
                scope_key=permission_link.scope_key,
                grant_type=grant.grant_type,
                grant_expires_at=grant.grant_expires_at,
            )


def _snapshot_app_actions(task: HandoverTask) -> None:
    # 交接面 = 当事人有授权痕迹的 APP, 加上声明了交接钩子的 APP。
    app_ids = {grant.app_id for grant in _latest_grants_per_app(task.subject_user)}
    hook_app_ids = set(
        AppWebhookConfig.objects.filter(enabled=True, app__is_active=True)
        .exclude(handover_url="")
        .values_list("app_id", flat=True),
    )
    for app in App.objects.filter(id__in=app_ids | hook_app_ids):
        _ = HandoverAppAction.objects.create(task=task, app=app)


def _latest_grants_per_app(subject: UserMirror) -> list[AccessGrant]:
    # 自动离职单建单时授权已被立即撤销(is_current=False): 快照取每 APP 最新一行
    # (含刚撤销的), 手动提前建单时最新行即 active current 行, 两种路径同一口径。
    grants = (
        AccessGrant.objects.select_related("app")
        .filter(user=subject, app__is_active=True)
        .order_by("app_id", "-version", "-id")
    )
    latest: dict[int, AccessGrant] = {}
    for grant in grants:
        if grant.app_id not in latest:
            latest[grant.app_id] = grant
    return list(latest.values())


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


def _schedule_account_disable(subject: UserMirror) -> None:
    # Authentik 禁号/吊销会话走 Celery(可重试), 不阻塞目录同步事务。
    user_pk = int(subject.pk)
    transaction.on_commit(
        lambda: current_app.send_task(DISABLE_ACCOUNT_TASK_NAME, args=[user_pk]),
    )


def _ensure_action_operable(action: HandoverAppAction) -> None:
    if action.task.status not in TASK_OPEN_STATUSES:
        raise HandoverConflictError(TASK_NOT_OPEN_MESSAGE)
    if action.status == ACTION_STATUS_DONE:
        raise HandoverConflictError(TASK_NOT_OPEN_MESSAGE)


def _releases_to_pool(action: HandoverAppAction) -> bool:
    return action.policy.get("unowned_strategy") == "release_to_pool"


def _handover_hook_url(app: App) -> str:
    config = AppWebhookConfig.objects.filter(app=app, enabled=True).first()
    if config is None:
        return ""
    return config.handover_url


def _hook_payload(action: HandoverAppAction, *, mode: str) -> dict[str, JsonValue]:
    task = action.task
    policy: dict[str, JsonValue] = dict(action.policy)
    if "unowned_strategy" not in policy:
        policy["unowned_strategy"] = "transfer"
    return {
        # task_id 是幂等键: 同一交接单对同一 APP 重复 execute 必须安全。
        "task_id": f"{task.id}:{action.app.app_key}",
        "kind": task.kind,
        "from_user_id": task.subject_user.authentik_user_id,
        "to_user_id": (
            action.to_user.authentik_user_id if action.to_user is not None else None
        ),
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
    selected = [item for item in items if item.selected]
    _ = HandoverGrantItem.objects.filter(id__in=[i.id for i in unselected]).update(
        status=ITEM_STATUS_SKIPPED,
    )
    if action.to_user is None or not selected:
        _ = HandoverGrantItem.objects.filter(id__in=[i.id for i in selected]).update(
            status=ITEM_STATUS_SKIPPED,
        )
        return 0
    groups = [item.authorization_group for item in selected if item.authorization_group]
    direct_grants = [
        ScopedDirectGrantInput(permission=item.permission, scope_key=item.scope_key)
        for item in selected
        if item.permission is not None
    ]
    # 类型与期限照抄原授权(§7 决策 12): 任一 permanent → permanent, 否则取最长期限。
    grant_type = (
        GRANT_TYPE_PERMANENT
        if any(item.grant_type == GRANT_TYPE_PERMANENT for item in selected)
        else GRANT_TYPE_TIMED
    )
    expires_at = None
    if grant_type == GRANT_TYPE_TIMED:
        expiries = [item.grant_expires_at for item in selected if item.grant_expires_at]
        expires_at = max(expiries) if expiries else timezone.now() + timedelta(days=30)
    _ = _merge_into_current_grant(
        user=action.to_user,
        app=action.app,
        groups=groups,
        direct_grants=direct_grants,
        grant_type=grant_type,
        grant_expires_at=expires_at,
        actor_id=f"handover_task:{action.task_id}",
    )
    _ = HandoverGrantItem.objects.filter(id__in=[i.id for i in selected]).update(
        status=ITEM_STATUS_DONE,
    )
    return len(selected)


def _merge_into_current_grant(  # noqa: PLR0913 - 合并授权的完整业务事实。
    *,
    user: UserMirror,
    app: App,
    groups: list[AuthorizationGroup],
    direct_grants: list[ScopedDirectGrantInput],
    grant_type: str,
    grant_expires_at: datetime | None,
    actor_id: str,
) -> AccessGrant:
    # 接收人已有 current 授权时合并(change), 否则新建; 授权来源经审计 actor_id 可溯源到交接单。
    existing = AccessGrant.objects.filter(user=user, app=app, is_current=True).first()
    merged_groups: dict[int, AuthorizationGroup] = {group.id: group for group in groups}
    merged_direct: dict[tuple[int, str], ScopedDirectGrantInput] = {
        (direct.permission.id, direct.scope_key): direct for direct in direct_grants
    }
    effective_type = grant_type
    effective_expiry: datetime | None = grant_expires_at
    if existing is not None and existing.status == "active":
        for link in AccessGrantGroup.objects.select_related("authorization_group").filter(
            grant=existing,
        ):
            _ = merged_groups.setdefault(link.authorization_group.id, link.authorization_group)
        for permission_link in AccessGrantPermission.objects.select_related("permission").filter(
            grant=existing,
        ):
            key = (permission_link.permission.id, permission_link.scope_key)
            _ = merged_direct.setdefault(
                key,
                ScopedDirectGrantInput(
                    permission=permission_link.permission,
                    scope_key=permission_link.scope_key,
                ),
            )
        # 既有 permanent 优先; 双 timed 取更晚过期。
        if existing.grant_type == GRANT_TYPE_PERMANENT:
            effective_type = GRANT_TYPE_PERMANENT
            effective_expiry = None
        elif effective_type == GRANT_TYPE_TIMED and existing.grant_expires_at is not None:
            if effective_expiry is None or existing.grant_expires_at > effective_expiry:
                effective_expiry = existing.grant_expires_at
    input_data = GrantMutationInput(
        user=user,
        app=app,
        grant_type=cast("GrantType", effective_type),
        grant_expires_at=effective_expiry,
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
    groups: dict[int, AuthorizationGroup] = {}
    direct: dict[tuple[int, str], ScopedDirectGrantInput] = {}
    grant_type = GRANT_TYPE_PERMANENT
    expires_at = None
    if existing is not None and existing.status == "active":
        grant_type = existing.grant_type
        expires_at = existing.grant_expires_at
        _collect_kept_targets(
            existing=existing,
            app_key=app_key,
            revoke_keys=revoke_keys,
            groups=groups,
            direct=direct,
        )
    for item in add_items:
        if item.authorization_group is not None:
            groups[item.authorization_group.id] = item.authorization_group
        if item.permission is not None:
            direct[(item.permission.id, item.scope_key)] = ScopedDirectGrantInput(
                permission=item.permission,
                scope_key=item.scope_key,
            )
    input_data = GrantMutationInput(
        user=subject,
        app=app,
        grant_type=cast("GrantType", grant_type),
        grant_expires_at=expires_at,
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


def _collect_kept_targets(
    *,
    existing: AccessGrant,
    app_key: str,
    revoke_keys: set[str],
    groups: dict[int, AuthorizationGroup],
    direct: dict[tuple[int, str], ScopedDirectGrantInput],
) -> None:
    for link in AccessGrantGroup.objects.select_related("authorization_group").filter(
        grant=existing,
    ):
        key = f"{app_key}:group:{link.authorization_group.key}"
        if key not in revoke_keys:
            groups[link.authorization_group.id] = link.authorization_group
    for permission_link in AccessGrantPermission.objects.select_related("permission").filter(
        grant=existing,
    ):
        key = (
            f"{app_key}:permission:{permission_link.permission.key}"
            f":{permission_link.scope_key}"
        )
        if key not in revoke_keys:
            direct[(permission_link.permission.id, permission_link.scope_key)] = (
                ScopedDirectGrantInput(
                    permission=permission_link.permission,
                    scope_key=permission_link.scope_key,
                )
            )


def _grant_item_key(item: HandoverGrantItem) -> str:
    if item.authorization_group is not None:
        return f"{item.app.app_key}:group:{item.authorization_group.key}"
    permission = item.permission
    permission_key = permission.key if permission is not None else ""
    return f"{item.app.app_key}:permission:{permission_key}:{item.scope_key}"


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


def _merged_grant_type(items: list[OnboardingTemplateItem]) -> str:
    if any(item.grant_type == GRANT_TYPE_PERMANENT for item in items):
        return GRANT_TYPE_PERMANENT
    return GRANT_TYPE_TIMED


def _merged_expiry(items: list[OnboardingTemplateItem]) -> datetime | None:
    if _merged_grant_type(items) == GRANT_TYPE_PERMANENT:
        return None
    days = max((item.duration_days or 30) for item in items)
    return timezone.now() + timedelta(days=days)


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


