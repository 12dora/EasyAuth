from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from easyauth.accounts.models import USER_STATUS_DEPARTED, UserMirror
from easyauth.accounts.services import AuthentikSyncService
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.audit.models import AuditLog
from easyauth.grants.inputs import ScopedDirectGrantInput
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission
from easyauth.grants.services import GrantMutationInput, GrantService
from easyauth.lifecycle import services as lifecycle_services
from easyauth.lifecycle.models import (
    HANDOVER_KIND_TRANSFER,
    HandoverAppAction,
    HandoverGrantItem,
    HandoverTask,
    HandoverTeamItem,
    OnboardingTemplate,
    OnboardingTemplateItem,
)
from easyauth.lifecycle.services import (
    build_transfer_grant_diff,
    confirm_transfer_grant_diff,
    ensure_handover_task,
    execute_action,
    onboard_user,
    start_offboarding,
    update_action_receiver,
)
from easyauth.teams.models import Team, TeamMember
from easyauth.webhooks.models import AppWebhookConfig

if TYPE_CHECKING:
    from easyauth.applications.ops_models import JsonValue

pytestmark = pytest.mark.django_db


def _app_with_catalog(app_key: str) -> tuple[App, AuthorizationGroup, Permission]:
    app = App.objects.create(app_key=app_key, name=app_key)
    scope = AppScope.objects.create(app=app, key="GLOBAL", name="Global")
    group = AuthorizationGroup.objects.create(app=app, key="sales", kind="role", name="销售")
    permission = Permission.objects.create(
        app=app,
        key="customer.view",
        name="客户查看",
        supported_scopes=[scope.key],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key=scope.key,
    )
    return app, group, permission


def _granted_user(user_id: str, app: App, group: AuthorizationGroup) -> UserMirror:
    user = UserMirror.objects.create(authentik_user_id=user_id, name=user_id)
    _ = GrantService.create_grant(
        GrantMutationInput(user=user, app=app, authorization_groups=(group,)),
    )
    return user


def test_start_offboarding_creates_task_snapshot_and_removes_teams() -> None:
    # Given: 当事人有授权、是一个团队的 leader、另一个团队的成员。
    app, group, _permission = _app_with_catalog("lc-offboard-app")
    subject = _granted_user("lc-offboard-user", app, group)
    led_team = Team.objects.create(name="lc-led-team")
    _ = TeamMember.objects.create(team=led_team, user=subject, role="leader")
    member_team = Team.objects.create(name="lc-member-team")
    _ = TeamMember.objects.create(team=member_team, user=subject, role="member")

    # When
    result = start_offboarding(subject)

    # Then: 建单+授权快照+leader 团队列入交接单+移出所有团队; 重复调用幂等。
    task = result.task
    assert result.created is True
    assert task.kind == "offboard"
    assert HandoverGrantItem.objects.filter(task=task).count() == 1
    assert HandoverAppAction.objects.filter(task=task, app=app).exists()
    team_items = list(HandoverTeamItem.objects.filter(task=task))
    assert [entry.team.name for entry in team_items] == ["lc-led-team"]
    assert not TeamMember.objects.filter(user=subject).exists()
    repeat = start_offboarding(subject)
    assert repeat.created is False
    assert repeat.task.id == task.id
    assert AuditLog.objects.filter(event_type="handover_task_created").count() == 1


def test_execute_action_transfers_selected_grants_and_calls_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 交接单含两条快照(一条取消勾选), APP 声明了交接钩子, 接收人已有部分授权。
    app, group, permission = _app_with_catalog("lc-exec-app")
    subject = UserMirror.objects.create(authentik_user_id="lc-exec-user")
    _ = GrantService.create_grant(
        GrantMutationInput(
            user=subject,
            app=app,
            authorization_groups=(group,),
            direct_grants=(ScopedDirectGrantInput(permission=permission, scope_key="GLOBAL"),),
        ),
    )
    receiver = UserMirror.objects.create(authentik_user_id="lc-exec-receiver")
    _ = AppWebhookConfig.objects.create(
        app=app,
        secret="whsec-lc",  # noqa: S106 - 测试用密钥。
        handover_url="https://etrade.example.com/api/v1/easyauth/lifecycle/handover",
    )
    task, _created = ensure_handover_task(
        subject=subject,
        kind="offboard",
        created_by="admin-a",
    )
    items = list(HandoverGrantItem.objects.filter(task=task).order_by("id"))
    direct_item = next(item for item in items if item.permission is not None)
    direct_item.selected = False
    direct_item.save(update_fields=["selected"])
    action = HandoverAppAction.objects.get(task=task, app=app)
    action = update_action_receiver(action=action, to_user=receiver, policy={})
    hook_calls: list[dict[str, JsonValue]] = []

    def fake_hook(
        *,
        app: App,  # noqa: ARG001
        url: str,  # noqa: ARG001
        event_type: str,
        delivery_id: str,  # noqa: ARG001
        payload: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        hook_calls.append({"event_type": event_type, **payload})
        return {"summary": {"customers_transferred": 23}}

    monkeypatch.setattr(lifecycle_services, "signed_hook_post", fake_hook)

    # When
    action = execute_action(action)

    # Then: 勾选项转授给接收人(未勾选跳过), 钩子按协议收到 execute 载荷, 单据完成。
    assert action.status == "done"
    assert action.result_payload == {"summary": {"customers_transferred": 23}}
    receiver_grant = AccessGrant.objects.get(user=receiver, app=app, is_current=True)
    assert AccessGrantGroup.objects.filter(grant=receiver_grant, authorization_group=group).exists()
    assert not AccessGrantPermission.objects.filter(grant=receiver_grant).exists()
    direct_item.refresh_from_db()
    assert direct_item.status == "skipped"
    call = hook_calls[0]
    assert call["event_type"] == "lifecycle.handover.execute"
    assert call["kind"] == "offboard"
    assert call["from_user_id"] == "lc-exec-user"
    assert call["to_user_id"] == "lc-exec-receiver"
    task.refresh_from_db()
    assert task.status == "completed"


def test_execute_action_requires_receiver_or_release_policy() -> None:
    # Given: 未指定接收人也未选择释放公海。
    app, group, _permission = _app_with_catalog("lc-noreceiver-app")
    subject = _granted_user("lc-noreceiver-user", app, group)
    task, _created = ensure_handover_task(
        subject=subject,
        kind="offboard",
        created_by="admin-a",
    )
    action = HandoverAppAction.objects.get(task=task, app=app)

    # When / Then: 缓冲是常态, 不允许无接收策略执行。
    with pytest.raises(lifecycle_services.HandoverError):
        _ = execute_action(action)
    action.refresh_from_db()
    assert action.status == "pending"
    task.refresh_from_db()
    assert task.status == "pending"


def test_transfer_grant_diff_build_and_confirm() -> None:
    # Given: 转岗单 + 新岗位模板(保留 group、新增权限), 当事人现有 group+直接权限。
    app, group, permission = _app_with_catalog("lc-transfer-app")
    extra_permission = Permission.objects.create(
        app=app,
        key="order.view",
        name="订单查看",
        supported_scopes=["GLOBAL"],
    )
    subject = UserMirror.objects.create(authentik_user_id="lc-transfer-user")
    _ = GrantService.create_grant(
        GrantMutationInput(
            user=subject,
            app=app,
            authorization_groups=(group,),
            direct_grants=(ScopedDirectGrantInput(permission=permission, scope_key="GLOBAL"),),
        ),
    )
    template = OnboardingTemplate.objects.create(name="新岗位模板")
    _ = OnboardingTemplateItem.objects.create(
        template=template,
        app=app,
        authorization_group=group,
    )
    _ = OnboardingTemplateItem.objects.create(
        template=template,
        app=app,
        permission=extra_permission,
        scope_key="GLOBAL",
    )
    task, _created = ensure_handover_task(
        subject=subject,
        kind=HANDOVER_KIND_TRANSFER,
        created_by="admin-a",
    )

    # When: 生成差异并全选确认。
    plan = build_transfer_grant_diff(task=task, template=template)
    revoke_keys = [
        entry["key"]
        for entry in plan.grant_diff["revoke"]
        if isinstance(entry, dict) and isinstance(entry.get("key"), str)
    ]
    add_keys = [
        entry["key"]
        for entry in plan.grant_diff["add"]
        if isinstance(entry, dict) and isinstance(entry.get("key"), str)
    ]
    plan = confirm_transfer_grant_diff(
        task=task,
        revoke_keys=revoke_keys,
        add_keys=add_keys,
        actor_id="admin-a",
    )

    # Then: 旧直接权限被收回、新权限生效、保留的 group 未动; 账号保持可用。
    grant = AccessGrant.objects.get(user=subject, app=app, is_current=True)
    assert plan.confirmed_at is not None
    assert AccessGrantGroup.objects.filter(grant=grant, authorization_group=group).exists()
    permission_keys = set(
        AccessGrantPermission.objects.filter(grant=grant).values_list(
            "permission__key",
            flat=True,
        ),
    )
    assert permission_keys == {"order.view"}
    subject.refresh_from_db()
    assert subject.status == "active"


def test_onboard_user_creates_grants_from_template() -> None:
    # Given: 岗位模板含 group 与直接权限。
    app, group, permission = _app_with_catalog("lc-onboard-app")
    template = OnboardingTemplate.objects.create(name="销售岗模板")
    _ = OnboardingTemplateItem.objects.create(
        template=template,
        app=app,
        authorization_group=group,
    )
    _ = OnboardingTemplateItem.objects.create(
        template=template,
        app=app,
        permission=permission,
        scope_key="GLOBAL",
    )
    newcomer = UserMirror.objects.create(authentik_user_id="lc-newcomer")

    # When
    grants = onboard_user(user=newcomer, template=template, actor_id="admin-a")

    # Then: 一键套用模板批量授权(每 APP 一条 current 授权)。
    assert len(grants) == 1
    grant = AccessGrant.objects.get(user=newcomer, app=app, is_current=True)
    assert AccessGrantGroup.objects.filter(grant=grant).count() == 1
    assert AccessGrantPermission.objects.filter(grant=grant).count() == 1
    assert AuditLog.objects.filter(event_type="lifecycle_onboarded").exists()


def test_manual_offboard_task_for_active_user_keeps_account_active() -> None:
    # Given: 在职员工。
    app, group, _permission = _app_with_catalog("lc-manual-app")
    subject = _granted_user("lc-manual-user", app, group)

    # When: 管理员提前手动建离职交接单(不触发立即项)。
    task, created = ensure_handover_task(
        subject=subject,
        kind="offboard",
        created_by="admin-a",
        reason="离职前主动交接",
    )

    # Then: 建单成功, 账号与授权不受影响。
    subject.refresh_from_db()
    assert created is True
    assert task.status == "pending"
    assert subject.status != USER_STATUS_DEPARTED
    assert AccessGrant.objects.filter(user=subject, is_current=True, status="active").exists()


def test_offboard_snapshot_survives_prior_revocation() -> None:
    # Given: 目录同步已按离职回收撤销授权(is_current=False), 之后才建交接单。
    app, group, _permission = _app_with_catalog("lc-revoked-app")
    subject = _granted_user("lc-revoked-user", app, group)
    _ = AuthentikSyncService.apply_directory_status(subject, USER_STATUS_DEPARTED)
    assert not AccessGrant.objects.filter(user=subject, is_current=True).exists()

    # When: 离职编排建单。
    result = start_offboarding(subject)

    # Then: 快照基于撤销前的最新授权行, 不为空(§7 决策 12)。
    items = list(HandoverGrantItem.objects.filter(task=result.task))
    assert len(items) == 1
    assert items[0].authorization_group is not None
    assert items[0].authorization_group.key == "sales"


def test_open_task_is_unique_per_subject() -> None:
    # Given
    app, group, _permission = _app_with_catalog("lc-unique-app")
    subject = _granted_user("lc-unique-user", app, group)
    first, _ = ensure_handover_task(subject=subject, kind="offboard", created_by="a")

    # When: 再建转岗单(同一当事人已有进行中交接单)。
    second, created = ensure_handover_task(subject=subject, kind="transfer", created_by="a")

    # Then: 幂等返回既有单。
    assert created is False
    assert second.id == first.id
    assert HandoverTask.objects.filter(subject_user=subject).count() == 1


def test_transfer_completion_clears_department_changed_flag() -> None:
    # Given: 被标记"部门已变更"的当事人 + 已确认差异的转岗单, 全部 APP 动作已收尾。
    from django.utils import timezone

    from easyauth.lifecycle.models import ACTION_STATUS_SKIPPED
    from easyauth.lifecycle.services import refresh_task_status

    app, group, permission = _app_with_catalog("lc-clear-flag-app")
    subject = UserMirror.objects.create(
        authentik_user_id="lc-clear-flag-user",
        department="新部门",
        department_changed_at=timezone.now(),
    )
    _ = GrantService.create_grant(
        GrantMutationInput(
            user=subject,
            app=app,
            authorization_groups=(group,),
            direct_grants=(),
        ),
    )
    task, _created = ensure_handover_task(
        subject=subject,
        kind=HANDOVER_KIND_TRANSFER,
        created_by="admin-a",
    )
    template = OnboardingTemplate.objects.create(name="清理标记岗位模板")
    _ = OnboardingTemplateItem.objects.create(
        template=template,
        app=app,
        authorization_group=group,
    )
    plan = build_transfer_grant_diff(task=task, template=template)
    _ = confirm_transfer_grant_diff(
        task=task,
        revoke_keys=[
            entry["key"]
            for entry in plan.grant_diff["revoke"]
            if isinstance(entry, dict) and isinstance(entry.get("key"), str)
        ],
        add_keys=[],
        actor_id="admin-a",
    )
    _ = HandoverAppAction.objects.filter(task=task).update(status=ACTION_STATUS_SKIPPED)

    # When: 刷新任务状态到完成。
    refreshed = refresh_task_status(HandoverTask.objects.get(pk=task.pk))

    # Then: 转岗单完成, "部门已变更"提示被清除。
    assert refreshed.status == "completed"
    subject.refresh_from_db()
    assert subject.department_changed_at is None


def test_delete_task_only_after_cancelled_and_records_audit() -> None:
    # Given: 进行中的转岗单。
    from easyauth.lifecycle.services import HandoverConflictError, cancel_task, delete_task

    app, group, _permission = _app_with_catalog("lc-delete-app")
    subject = UserMirror.objects.create(authentik_user_id="lc-delete-user")
    _ = GrantService.create_grant(
        GrantMutationInput(
            user=subject,
            app=app,
            authorization_groups=(group,),
            direct_grants=(),
        ),
    )
    task, _created = ensure_handover_task(
        subject=subject,
        kind=HANDOVER_KIND_TRANSFER,
        created_by="admin-a",
    )

    # Then: 未取消不允许删除。
    with pytest.raises(HandoverConflictError):
        delete_task(task, actor_id="admin-a")

    # When: 取消后删除。
    _ = cancel_task(task, actor_id="admin-a")
    delete_task(task, actor_id="admin-a")

    # Then: 单据消失, 审计保留删除痕迹。
    assert not HandoverTask.objects.filter(pk=task.pk).exists()
    assert AuditLog.objects.filter(event_type="handover_task_deleted").exists()


def test_local_admin_cannot_be_handover_subject() -> None:
    # Given: 内置本地管理员的用户镜像。
    from easyauth.lifecycle.services import HandoverConflictError

    subject = UserMirror.objects.create(authentik_user_id="local-admin:admin")

    # Then: 离职/转岗建单一律拒绝(误操作会禁掉 break-glass 入口)。
    with pytest.raises(HandoverConflictError):
        _ = ensure_handover_task(subject=subject, kind=HANDOVER_KIND_TRANSFER, created_by="a")
    with pytest.raises(HandoverConflictError):
        _ = start_offboarding(subject, created_by="admin-a")
