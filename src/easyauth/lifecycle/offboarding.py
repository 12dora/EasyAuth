from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final, cast

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import UserMirror
from easyauth.applications.handover_capability import _seed_asset_type_placeholders
from easyauth.applications.models import (
    HANDOVER_CAPABILITY_DECLARED,
    HANDOVER_CAPABILITY_NONE,
    App,
    AppScope,
)
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission
from easyauth.lifecycle.assignee import apply_assignee, resolve_assignee
from easyauth.lifecycle.core import (
    LIFECYCLE_ACTOR_ID,
    TASK_KIND_CONFLICT_MESSAGE,
    record_task_event,
    refresh_task_status,
)
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover import initial_action_status_for_app
from easyauth.lifecycle.models import (
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_PENDING,
    ACTION_STATUS_SKIPPED,
    HANDOVER_ESCALATION_DAYS,
    HANDOVER_KIND_OFFBOARD,
    HANDOVER_KIND_PRE_OFFBOARD,
    HANDOVER_KIND_REASSIGN,
    HANDOVER_KIND_TRANSFER,
    TASK_OPEN_STATUSES,
    HandoverAppAction,
    HandoverGrantItem,
    HandoverTask,
    HandoverTeamItem,
    TransferPlan,
)
from easyauth.lifecycle.tasks import DISABLE_ACCOUNT_TASK_NAME
from easyauth.outbox.services import enqueue_task
from easyauth.teams.models import TEAM_MEMBER_ROLE_LEADER, TeamMember


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
    app_keys: tuple[str, ...] | None = None,
) -> tuple[HandoverTask, bool]:
    """建单(幂等): 同一当事人已有进行中交接单时直接返回既有单。"""
    _assert_lifecycle_subject(subject)
    subject_pk = cast("int", subject.pk)
    with transaction.atomic():
        subject = UserMirror.objects.select_for_update().get(pk=subject_pk)
        # reassign 可与其他 open 单并存; 生命周期类单据一人一张。
        if kind == HANDOVER_KIND_REASSIGN:
            existing = None
        else:
            existing = (
                HandoverTask.objects.select_for_update()
                .filter(
                    subject_user=subject,
                    status__in=TASK_OPEN_STATUSES,
                    kind__in=(
                        HANDOVER_KIND_OFFBOARD,
                        HANDOVER_KIND_TRANSFER,
                        HANDOVER_KIND_PRE_OFFBOARD,
                    ),
                )
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
            generation=1,
        )
        resolution = resolve_assignee(subject)
        if kind == HANDOVER_KIND_PRE_OFFBOARD and created_by == subject.authentik_user_id:
            from easyauth.lifecycle.models import ASSIGNEE_STATE_SUBJECT

            task.assignee = subject
            task.assignee_state = ASSIGNEE_STATE_SUBJECT
            task.escalation_level = 0
            task.escalation_deadline = timezone.now() + timedelta(
                days=HANDOVER_ESCALATION_DAYS,
            )
            task.save(
                update_fields=[
                    "assignee",
                    "assignee_state",
                    "escalation_level",
                    "escalation_deadline",
                    "updated_at",
                ],
            )
            record_task_event(
                task,
                action="handover_assignee_assigned",
                actor_id=created_by,
                extra={"assignee_state": ASSIGNEE_STATE_SUBJECT},
            )
        else:
            _ = apply_assignee(
                task,
                resolution,
                actor_id=created_by,
                reason="task_created",
            )
        _snapshot_grant_items(task, grants=snapshot_grants)
        _snapshot_app_actions(task, grants=snapshot_grants, app_keys=app_keys)
        _snapshot_leader_teams(task)
        if kind == HANDOVER_KIND_TRANSFER:
            _ = TransferPlan.objects.create(task=task)
        record_task_event(task, action="handover_task_created", actor_id=created_by)
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
                generation=task.generation,
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
                generation=task.generation,
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


def _snapshot_app_actions(
    task: HandoverTask,
    *,
    grants: list[AccessGrant],
    app_keys: tuple[str, ...] | None = None,
) -> None:
    # 交接面 = 当事人有授权痕迹的 APP + 已声明交接能力的 APP; reassign 仅限 app_keys。
    if app_keys is not None:
        apps = list(App.objects.filter(app_key__in=app_keys, is_active=True))
    else:
        # 交接面 = 有授权痕迹的 APP + 已声明 capability 的 APP。
        # 有授权但 undeclared → blocked(不再静默成功)。
        app_ids = {grant.app_id for grant in grants}
        capability_app_ids = set(
            App.objects.filter(
                is_active=True,
                handover_capability__in=(
                    HANDOVER_CAPABILITY_DECLARED,
                    HANDOVER_CAPABILITY_NONE,
                ),
            ).values_list("id", flat=True),
        )
        apps = list(App.objects.filter(id__in=app_ids | capability_app_ids, is_active=True))
    for app in apps:
        status, blocked_reason, skip_reason, skipped_by = initial_action_status_for_app(app)
        action = HandoverAppAction.objects.create(
            task=task,
            app=app,
            app_key_snapshot=app.app_key,
            app_name_snapshot=app.name,
            app_catalog_version_snapshot=app.catalog_version,
            generation=task.generation,
            status=status,
            blocked_reason=blocked_reason,
            skip_reason=skip_reason,
            skipped_by=skipped_by,
            skipped_at=timezone.now() if status == ACTION_STATUS_SKIPPED else None,
        )
        if status == ACTION_STATUS_BLOCKED:
            record_task_event(
                task,
                action="handover_action_blocked",
                actor_id=LIFECYCLE_ACTOR_ID,
                actor_type="system",
                extra={"app_key": app.app_key, "blocked_reason": blocked_reason},
            )
        if status == ACTION_STATUS_PENDING:
            _seed_asset_type_placeholders(action)


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
        record_task_event(
            task,
            action="handover_memberships_removed",
            actor_id=LIFECYCLE_ACTOR_ID,
            extra={"removed_count": removed},
        )
    return removed


def _schedule_account_disable(subject: UserMirror, *, task: HandoverTask) -> None:
    # Authentik 禁号/吊销会话走 Celery(可重试), 不阻塞目录同步事务。
    user_pk = cast("int", subject.pk)
    _ = enqueue_task(
        event_key=f"lifecycle-disable-account:{task.id}",
        task_name=DISABLE_ACCOUNT_TASK_NAME,
        args=[user_pk],
    )
