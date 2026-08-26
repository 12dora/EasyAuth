"""交接单授权、应用动作与主管团队快照。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Q
from django.utils import timezone

from easyauth.applications.models import (
    HANDOVER_CAPABILITY_DECLARED,
    HANDOVER_CAPABILITY_NONE,
    App,
    AppScope,
)
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission
from easyauth.lifecycle.core import LIFECYCLE_ACTOR_ID, record_task_event
from easyauth.lifecycle.errors import HandoverError
from easyauth.lifecycle.handover_actions import (
    initial_action_status_for_app,
    seed_asset_type_placeholders,
)
from easyauth.lifecycle.models import (
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_PENDING,
    ACTION_STATUS_SKIPPED,
    HandoverAppAction,
    HandoverGrantItem,
    HandoverTask,
    HandoverTeamItem,
)
from easyauth.teams.models import TEAM_MEMBER_ROLE_LEADER, TeamMember

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.accounts.models import UserMirror


def snapshot_grant_items(task: HandoverTask, *, grants: list[AccessGrant]) -> None:
    now = timezone.now()
    for grant in grants:
        _snapshot_group_grant_items(task, grant=grant, now=now)
        _snapshot_permission_grant_items(task, grant=grant, now=now)


def _snapshot_group_grant_items(
    task: HandoverTask,
    *,
    grant: AccessGrant,
    now: datetime,
) -> None:
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


def _snapshot_permission_grant_items(
    task: HandoverTask,
    *,
    grant: AccessGrant,
    now: datetime,
) -> None:
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


def snapshot_app_actions(
    task: HandoverTask,
    *,
    grants: list[AccessGrant],
    app_keys: tuple[str, ...] | None = None,
) -> None:
    # 交接面 = 当事人有授权痕迹的 APP + 已声明交接能力的 APP; reassign 仅限 app_keys。
    # 升级路径复用: get_or_create, 新发现的 APP 才初始化状态。
    apps = _resolve_apps_for_snapshot(grants=grants, app_keys=app_keys)
    for app in apps:
        _ensure_app_action(task, app)


def _resolve_apps_for_snapshot(
    *,
    grants: list[AccessGrant],
    app_keys: tuple[str, ...] | None,
) -> list[App]:
    if app_keys is not None:
        return resolve_requested_apps(app_keys)
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
    return list(App.objects.filter(id__in=app_ids | capability_app_ids, is_active=True))


def resolve_requested_apps(app_keys: tuple[str, ...]) -> list[App]:
    """解析显式 app_keys; 未知或停用的 key 一律失败, 禁止建出缺 action 的单。"""
    requested_keys = set(app_keys)
    apps = list(App.objects.filter(app_key__in=app_keys, is_active=True))
    resolved_active_keys = {app.app_key for app in apps}
    if requested_keys != resolved_active_keys:
        missing = requested_keys - resolved_active_keys
        message = f"应用不存在或已停用: {min(missing)}。"
        raise HandoverError(message)
    return apps


def _ensure_app_action(task: HandoverTask, app: App) -> None:
    status, blocked_reason, skip_reason, skipped_by = initial_action_status_for_app(app)
    action, created = HandoverAppAction.objects.get_or_create(
        task=task,
        app=app,
        defaults={
            "app_key_snapshot": app.app_key,
            "app_name_snapshot": app.name,
            "app_catalog_version_snapshot": app.catalog_version,
            "generation": task.generation,
            "status": status,
            "blocked_reason": blocked_reason,
            "skip_reason": skip_reason,
            "skipped_by": skipped_by,
            "skipped_at": timezone.now() if status == ACTION_STATUS_SKIPPED else None,
        },
    )
    if not created:
        return
    if status == ACTION_STATUS_BLOCKED:
        record_task_event(
            task,
            action="handover_action_blocked",
            actor_id=LIFECYCLE_ACTOR_ID,
            actor_type="system",
            extra={"app_key": app.app_key, "blocked_reason": blocked_reason},
        )
    if status == ACTION_STATUS_PENDING:
        seed_asset_type_placeholders(action)


def snapshot_grants(
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


def snapshot_leader_teams(task: HandoverTask) -> None:
    led_teams = TeamMember.objects.select_related("team").filter(
        user=task.subject_user,
        role=TEAM_MEMBER_ROLE_LEADER,
        team__is_active=True,
    )
    for membership in led_teams:
        _ = HandoverTeamItem.objects.get_or_create(task=task, team=membership.team)
