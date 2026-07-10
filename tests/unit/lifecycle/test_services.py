from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from django.utils import timezone

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
from easyauth.grants.inputs import AuthorizationGroupGrantInput, ScopedDirectGrantInput
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission
from easyauth.grants.services import GrantMutationInput, GrantService
from easyauth.lifecycle import services as lifecycle_services
from easyauth.lifecycle.models import (
    ACTION_STATUS_SKIPPED,
    HANDOVER_KIND_TRANSFER,
    HandoverAppAction,
    HandoverGrantItem,
    HandoverTask,
    HandoverTeamItem,
    OnboardingTemplate,
    OnboardingTemplateItem,
    TransferPlan,
)
from easyauth.lifecycle.services import (
    HandoverConflictError,
    build_transfer_grant_diff,
    cancel_task,
    confirm_transfer_grant_diff,
    delete_task,
    ensure_handover_task,
    execute_action,
    onboard_user,
    poll_async_action,
    refresh_task_status,
    start_offboarding,
    update_action_receiver,
)
from easyauth.outbox.models import OutboxEvent
from easyauth.teams.models import Team, TeamMember
from easyauth.webhooks.hooks import HookResponse
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
        GrantMutationInput(
            user=user,
            app=app,
            authorization_groups=(AuthorizationGroupGrantInput(group, None),),
        ),
    )
    return user


def _transfer_plan_with_replacement(
    prefix: str,
) -> tuple[HandoverTask, TransferPlan, AccessGrant]:
    app, group, old_permission = _app_with_catalog(f"{prefix}-app")
    new_permission = Permission.objects.create(
        app=app,
        key="order.view",
        name="订单查看",
        supported_scopes=["GLOBAL"],
    )
    subject = UserMirror.objects.create(authentik_user_id=f"{prefix}-user")
    grant = GrantService.create_grant(
        GrantMutationInput(
            user=subject,
            app=app,
            authorization_groups=(AuthorizationGroupGrantInput(group, None),),
            direct_grants=(
                ScopedDirectGrantInput(
                    permission=old_permission,
                    scope_key="GLOBAL",
                    expires_at=None,
                ),
            ),
        ),
    )
    template = OnboardingTemplate.objects.create(name=f"{prefix}-template")
    _ = OnboardingTemplateItem.objects.create(
        template=template,
        app=app,
        authorization_group=group,
    )
    _ = OnboardingTemplateItem.objects.create(
        template=template,
        app=app,
        permission=new_permission,
        scope_key="GLOBAL",
    )
    task, _created = ensure_handover_task(
        subject=subject,
        kind=HANDOVER_KIND_TRANSFER,
        created_by="admin-a",
    )
    return task, build_transfer_grant_diff(task=task, template=template), grant


def _plan_diff_keys(plan: TransferPlan, name: str) -> list[str]:
    entries = plan.grant_diff.get(name)
    if not isinstance(entries, list):
        return []
    return [
        entry["key"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("key"), str)
    ]


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
    disable_event = OutboxEvent.objects.get(event_key=f"lifecycle-disable-account:{task.id}")
    assert disable_event.args == [subject.id]


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
            authorization_groups=(AuthorizationGroupGrantInput(group, None),),
            direct_grants=(
                ScopedDirectGrantInput(
                    permission=permission,
                    scope_key="GLOBAL",
                    expires_at=None,
                ),
            ),
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
    ) -> HookResponse:
        hook_calls.append({"event_type": event_type, **payload})
        return HookResponse(
            status_code=200,
            location="",
            payload={"summary": {"customers_transferred": 23}},
        )

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


def test_execute_action_keeps_accepted_hook_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: APP 交接 hook 异步受理请求并返回状态 URL。
    app, group, _permission = _app_with_catalog("lc-async-hook-app")
    subject = _granted_user("lc-async-hook-user", app, group)
    receiver = UserMirror.objects.create(authentik_user_id="lc-async-hook-receiver")
    _ = AppWebhookConfig.objects.create(
        app=app,
        secret="whsec-async",  # noqa: S106 - 测试用密钥。
        handover_url="https://etrade.example.com/api/v1/easyauth/lifecycle/handover",
    )
    task, _created = ensure_handover_task(
        subject=subject,
        kind="offboard",
        created_by="admin-a",
    )
    action = update_action_receiver(
        action=HandoverAppAction.objects.get(task=task, app=app),
        to_user=receiver,
        policy={},
    )
    status_url = "https://etrade.example.com/api/v1/easyauth/lifecycle/status/1"

    def accepted_hook(
        *,
        app: App,  # noqa: ARG001
        url: str,  # noqa: ARG001
        event_type: str,  # noqa: ARG001
        delivery_id: str,  # noqa: ARG001
        payload: dict[str, JsonValue],  # noqa: ARG001
    ) -> HookResponse:
        return HookResponse(
            status_code=202,
            location=status_url,
            payload={"accepted": True},
        )

    monkeypatch.setattr(lifecycle_services, "signed_hook_post", accepted_hook)

    # When
    action = execute_action(action)

    # Then: 202 只表示受理, action 保持异步待完成并持久化查询地址。
    assert action.status == "async_pending"
    assert action.async_status_url == status_url
    assert action.result_payload == {"accepted": True}
    task.refresh_from_db()
    assert task.status != "completed"


def test_poll_async_action_completes_action_and_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 交接 hook 已返回 202, action 等待查询远端结果。
    app, group, _permission = _app_with_catalog("lc-async-poll-app")
    subject = _granted_user("lc-async-poll-user", app, group)
    receiver = UserMirror.objects.create(authentik_user_id="lc-async-poll-receiver")
    _ = AppWebhookConfig.objects.create(
        app=app,
        secret="whsec-async-poll",  # noqa: S106 - 测试用密钥。
        handover_url="https://etrade.example.com/api/v1/easyauth/lifecycle/handover",
    )
    task, _created = ensure_handover_task(
        subject=subject,
        kind="offboard",
        created_by="admin-a",
    )
    action = update_action_receiver(
        action=HandoverAppAction.objects.get(task=task, app=app),
        to_user=receiver,
        policy={},
    )
    status_url = "https://etrade.example.com/api/v1/easyauth/lifecycle/status/2"

    def accepted_hook(**_kwargs: object) -> HookResponse:
        return HookResponse(status_code=202, location=status_url, payload={"accepted": True})

    monkeypatch.setattr(lifecycle_services, "signed_hook_post", accepted_hook)
    pending = execute_action(action)
    assert pending.status == "async_pending"

    def completed_hook(**_kwargs: object) -> HookResponse:
        return HookResponse(
            status_code=200,
            location="",
            payload={"summary": {"customers_transferred": 23}},
        )

    monkeypatch.setattr(lifecycle_services, "signed_hook_get", completed_hook)

    # When
    completed = poll_async_action(pending)

    # Then: 200 完成 action、清理状态 URL 并驱动 task 收敛。
    assert completed.status == "done"
    assert completed.async_status_url == ""
    assert completed.async_poll_attempts == 1
    assert completed.result_payload == {"summary": {"customers_transferred": 23}}
    task.refresh_from_db()
    assert task.status == "completed"


def test_poll_async_action_rejects_attempts_at_limit_without_calling_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 异步查询已达有界重试上限。
    app, group, _permission = _app_with_catalog("lc-async-limit-app")
    subject = _granted_user("lc-async-limit-user", app, group)
    task, _created = ensure_handover_task(
        subject=subject,
        kind="offboard",
        created_by="admin-a",
    )
    action = HandoverAppAction.objects.get(task=task, app=app)
    action.status = "async_pending"
    action.async_status_url = "https://etrade.example.com/status/limit"
    max_attempts = 10
    action.async_poll_attempts = max_attempts
    action.save(
        update_fields=[
            "status",
            "async_status_url",
            "async_poll_attempts",
            "updated_at",
        ],
    )
    called = False

    def unexpected_hook(**_kwargs: object) -> HookResponse:
        nonlocal called
        called = True
        return HookResponse(status_code=200, location="", payload={})

    monkeypatch.setattr(lifecycle_services, "signed_hook_get", unexpected_hook)

    # When / Then: 上限检查在网络请求之前失败。
    with pytest.raises(lifecycle_services.HandoverConflictError):
        _ = poll_async_action(action)
    assert called is False
    action.refresh_from_db()
    assert action.async_poll_attempts == max_attempts
    assert action.status == "async_pending"


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


def test_failed_execution_locks_receiver_and_retry_uses_execution_receiver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 权限已转给 A 后 hook 失败的 action。
    app, group, _permission = _app_with_catalog("lc-fixed-receiver-app")
    subject = _granted_user("lc-fixed-receiver-user", app, group)
    receiver_a = UserMirror.objects.create(authentik_user_id="lc-receiver-a")
    receiver_b = UserMirror.objects.create(authentik_user_id="lc-receiver-b")
    _ = AppWebhookConfig.objects.create(
        app=app,
        secret="whsec-fixed-receiver",  # noqa: S106 - 测试用密钥。
        handover_url="https://etrade.example.com/api/v1/easyauth/lifecycle/handover",
    )
    task, _created = ensure_handover_task(
        subject=subject,
        kind="offboard",
        created_by="admin-a",
    )
    action = update_action_receiver(
        action=HandoverAppAction.objects.get(task=task, app=app),
        to_user=receiver_a,
        policy={},
    )
    hook_receivers: list[JsonValue] = []

    def flaky_hook(
        *,
        app: App,  # noqa: ARG001
        url: str,  # noqa: ARG001
        event_type: str,  # noqa: ARG001
        delivery_id: str,  # noqa: ARG001
        payload: dict[str, JsonValue],
    ) -> HookResponse:
        hook_receivers.append(payload["to_user_id"])
        if len(hook_receivers) == 1:
            message = "首次 hook 失败"
            raise lifecycle_services.HookCallError(message)
        return HookResponse(status_code=200, location="", payload={"ok": True})

    monkeypatch.setattr(lifecycle_services, "signed_hook_post", flaky_hook)
    with pytest.raises(lifecycle_services.HookCallError):
        _ = execute_action(action)
    action.refresh_from_db()
    assert action.execution_to_user_id == receiver_a.id
    assert action.execution_policy == {}
    assert HandoverGrantItem.objects.get(task=task, app=app).status == "done"

    # When / Then: 已开始执行后不能改为 B, 重试仍使用固化的 A。
    with pytest.raises(lifecycle_services.HandoverConflictError):
        _ = update_action_receiver(action=action, to_user=receiver_b, policy={})
    retried = execute_action(HandoverAppAction.objects.get(pk=action.pk))
    assert retried.status == "done"
    assert hook_receivers == [
        receiver_a.authentik_user_id,
        receiver_a.authentik_user_id,
    ]
    assert AccessGrant.objects.filter(user=receiver_a, app=app, is_current=True).exists()
    assert not AccessGrant.objects.filter(user=receiver_b, app=app).exists()


def test_action_receiver_and_release_policy_are_mutually_exclusive() -> None:
    # Given
    app, group, _permission = _app_with_catalog("lc-receiver-xor-app")
    subject = _granted_user("lc-receiver-xor-user", app, group)
    receiver = UserMirror.objects.create(authentik_user_id="lc-receiver-xor-target")
    task, _created = ensure_handover_task(
        subject=subject,
        kind="offboard",
        created_by="admin-a",
    )
    action = HandoverAppAction.objects.get(task=task, app=app)

    # Then: 接收人与释放公海严格 XOR。
    with pytest.raises(lifecycle_services.HandoverError):
        _ = update_action_receiver(
            action=action,
            to_user=receiver,
            policy={"unowned_strategy": "release_to_pool"},
        )


def test_action_receiver_cannot_be_handover_subject() -> None:
    # Given
    app, group, _permission = _app_with_catalog("lc-self-receiver-app")
    subject = _granted_user("lc-self-receiver-user", app, group)
    task, _created = ensure_handover_task(
        subject=subject,
        kind="offboard",
        created_by="admin-a",
    )
    action = HandoverAppAction.objects.get(task=task, app=app)

    # Then: 交接对象不能把授权转授给自己。
    with pytest.raises(lifecycle_services.HandoverError):
        _ = update_action_receiver(action=action, to_user=subject, policy={})


def test_expired_receiver_grant_is_not_merged_or_revived() -> None:
    # Given: 接收人的旧授权已过期, 但 beat 尚未将 active 状态归档。
    app, source_group, _permission = _app_with_catalog("lc-expired-receiver-app")
    stale_group = AuthorizationGroup.objects.create(
        app=app,
        key="stale",
        kind="role",
        name="已过期岗位",
    )
    subject = _granted_user("lc-expired-source", app, source_group)
    receiver = UserMirror.objects.create(authentik_user_id="lc-expired-receiver")
    expired = GrantService.create_grant(
        GrantMutationInput(
            user=receiver,
            app=app,
            authorization_groups=(
                AuthorizationGroupGrantInput(
                    stale_group,
                    timezone.now() + timedelta(days=1),
                ),
            ),
        ),
    )
    _ = AccessGrantGroup.objects.filter(
        grant=expired,
        authorization_group=stale_group,
    ).update(
        expires_at=timezone.now() - timedelta(seconds=1),
    )
    task, _created = ensure_handover_task(
        subject=subject,
        kind="offboard",
        created_by="admin-a",
    )
    action = update_action_receiver(
        action=HandoverAppAction.objects.get(task=task, app=app),
        to_user=receiver,
        policy={},
    )

    # When
    _ = execute_action(action)

    # Then: 旧授权先归档为 expired, 新授权不包含过期成员。
    expired.refresh_from_db()
    assert expired.status == "expired"
    assert expired.is_current is False
    current = AccessGrant.objects.get(user=receiver, app=app, is_current=True)
    assert set(
        AccessGrantGroup.objects.filter(grant=current).values_list(
            "authorization_group__key",
            flat=True,
        ),
    ) == {"sales"}


@pytest.mark.parametrize("status", ["skipped", "executing"])
def test_execute_action_rejects_non_operable_status(status: str) -> None:
    # Given: action 已跳过或正在执行。
    app, group, _permission = _app_with_catalog(f"lc-action-state-{status}")
    subject = _granted_user(f"lc-action-state-user-{status}", app, group)
    task, _created = ensure_handover_task(
        subject=subject,
        kind="offboard",
        created_by="admin-a",
    )
    action = HandoverAppAction.objects.get(task=task, app=app)
    action.status = status
    action.save(update_fields=["status", "updated_at"])

    # When / Then: 状态机拒绝不可操作状态, 不会二次执行。
    with pytest.raises(lifecycle_services.HandoverConflictError):
        _ = execute_action(action)
    assert HandoverAppAction.objects.get(pk=action.pk).status == status


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
            authorization_groups=(AuthorizationGroupGrantInput(group, None),),
            direct_grants=(
                ScopedDirectGrantInput(
                    permission=permission,
                    scope_key="GLOBAL",
                    expires_at=None,
                ),
            ),
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


@pytest.mark.parametrize("terminal_status", ["cancelled", "completed"])
def test_transfer_diff_confirmation_rejects_terminal_task(
    terminal_status: str,
) -> None:
    # Given: 已生成差异的转岗单进入终态。
    task, plan, original_grant = _transfer_plan_with_replacement(
        f"lc-terminal-{terminal_status}",
    )
    _ = HandoverTask.objects.filter(pk=task.pk).update(status=terminal_status)
    revoke_keys = _plan_diff_keys(plan, "revoke")
    add_keys = _plan_diff_keys(plan, "add")

    # When / Then: 终态后不得再改写授权。
    with pytest.raises(lifecycle_services.HandoverConflictError):
        _ = confirm_transfer_grant_diff(
            task=HandoverTask.objects.get(pk=task.pk),
            revoke_keys=revoke_keys,
            add_keys=add_keys,
            actor_id="admin-a",
        )
    original_grant.refresh_from_db()
    assert original_grant.is_current is True
    assert original_grant.version == 1


def test_transfer_diff_confirmation_is_idempotent_for_same_payload() -> None:
    # Given: 一份已确认的转岗差异。
    task, plan, _original_grant = _transfer_plan_with_replacement("lc-diff-idempotent")
    revoke_keys = _plan_diff_keys(plan, "revoke")
    add_keys = _plan_diff_keys(plan, "add")
    confirmed = confirm_transfer_grant_diff(
        task=task,
        revoke_keys=revoke_keys,
        add_keys=add_keys,
        actor_id="admin-a",
    )
    current = AccessGrant.objects.get(
        user=task.subject_user,
        app__app_key="lc-diff-idempotent-app",
        is_current=True,
    )
    confirmed_at = confirmed.confirmed_at
    current_version = current.version

    # When: 同一载荷重试。
    repeated = confirm_transfer_grant_diff(
        task=HandoverTask.objects.get(pk=task.pk),
        revoke_keys=list(reversed(revoke_keys)),
        add_keys=list(reversed(add_keys)),
        actor_id="admin-a",
    )

    # Then: 返回原确认事实, 不再增加授权版本或重写时间。
    assert repeated.id == confirmed.id
    assert repeated.confirmed_at == confirmed_at
    current.refresh_from_db()
    assert current.version == current_version
    assert AuditLog.objects.filter(event_type="handover_grant_diff_confirmed").count() == 1


def test_transfer_diff_confirmation_conflicts_for_different_payload() -> None:
    # Given: 转岗差异已按原载荷确认。
    task, plan, _original_grant = _transfer_plan_with_replacement("lc-diff-conflict")
    revoke_keys = _plan_diff_keys(plan, "revoke")
    add_keys = _plan_diff_keys(plan, "add")
    _ = confirm_transfer_grant_diff(
        task=task,
        revoke_keys=revoke_keys,
        add_keys=add_keys,
        actor_id="admin-a",
    )

    # When / Then: 相同 plan 上的异载荷不能被当作幂等重试。
    with pytest.raises(lifecycle_services.HandoverConflictError):
        _ = confirm_transfer_grant_diff(
            task=HandoverTask.objects.get(pk=task.pk),
            revoke_keys=[],
            add_keys=add_keys,
            actor_id="admin-a",
        )


def test_transfer_diff_confirmation_rejects_unknown_keys() -> None:
    # Given
    task, plan, original_grant = _transfer_plan_with_replacement("lc-diff-unknown")
    add_keys = _plan_diff_keys(plan, "add")

    # When / Then: 任何未知 key 都快速失败, 不能静默过滤后部分执行。
    with pytest.raises(lifecycle_services.HandoverError):
        _ = confirm_transfer_grant_diff(
            task=task,
            revoke_keys=["unknown-app:group:unknown"],
            add_keys=add_keys,
            actor_id="admin-a",
        )
    original_grant.refresh_from_db()
    assert original_grant.is_current is True
    assert TransferPlan.objects.get(pk=plan.pk).confirmed_at is None


def test_transfer_diff_confirmation_rolls_back_all_apps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 转岗差异需要同时撤销两个 App 的授权。
    app_a, group_a, _permission = _app_with_catalog("lc-atomic-a")
    app_b, group_b, _permission = _app_with_catalog("lc-atomic-b")
    subject = _granted_user("lc-atomic-user", app_a, group_a)
    grant_a = AccessGrant.objects.get(user=subject, app=app_a, is_current=True)
    grant_b = GrantService.create_grant(
        GrantMutationInput(
            user=subject,
            app=app_b,
            authorization_groups=(AuthorizationGroupGrantInput(group_b, None),),
        ),
    )
    task, _created = ensure_handover_task(
        subject=subject,
        kind=HANDOVER_KIND_TRANSFER,
        created_by="admin-a",
    )
    template = OnboardingTemplate.objects.create(name="lc-atomic-empty-template")
    plan = build_transfer_grant_diff(task=task, template=template)
    revoke_keys = _plan_diff_keys(plan, "revoke")
    original_revoke = GrantService.revoke_grant
    call_count = 0
    failure_call = 2

    def fail_second_revoke(
        *,
        user: UserMirror,
        app: App,
        actor_type: str,
        actor_id: str,
        reason: str = "",
    ) -> AccessGrant | None:
        nonlocal call_count
        call_count += 1
        if call_count == failure_call:
            message = "第二个 App 写入失败"
            raise RuntimeError(message)
        return original_revoke(
            user=user,
            app=app,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
        )

    monkeypatch.setattr(GrantService, "revoke_grant", staticmethod(fail_second_revoke))

    # When: 第二个 App 变更失败。
    with pytest.raises(RuntimeError, match="第二个 App"):
        _ = confirm_transfer_grant_diff(
            task=task,
            revoke_keys=revoke_keys,
            add_keys=[],
            actor_id="admin-a",
        )

    # Then: 第一个 App 的变更也回滚, plan 仍未确认。
    grant_a.refresh_from_db()
    grant_b.refresh_from_db()
    assert grant_a.status == "active"
    assert grant_a.is_current is True
    assert grant_b.status == "active"
    assert grant_b.is_current is True
    assert grant_a.version == 1
    assert grant_b.version == 1
    assert TransferPlan.objects.get(pk=plan.pk).confirmed_at is None


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


def test_onboard_user_preserves_each_membership_expiration() -> None:
    # Given: 同一 App 的模板同时含 30 天、365 天与永久成员。
    app, short_group, permanent_permission = _app_with_catalog("lc-item-expiry-app")
    long_group = AuthorizationGroup.objects.create(
        app=app,
        key="long-term",
        kind="role",
        name="长期岗位",
    )
    template = OnboardingTemplate.objects.create(name="逐项期限模板")
    _ = OnboardingTemplateItem.objects.create(
        template=template,
        app=app,
        authorization_group=short_group,
        grant_type="timed",
        duration_days=30,
    )
    _ = OnboardingTemplateItem.objects.create(
        template=template,
        app=app,
        authorization_group=long_group,
        grant_type="timed",
        duration_days=365,
    )
    _ = OnboardingTemplateItem.objects.create(
        template=template,
        app=app,
        permission=permanent_permission,
        scope_key="GLOBAL",
        grant_type="permanent",
    )
    newcomer = UserMirror.objects.create(authentik_user_id="lc-item-expiry-user")
    before = timezone.now()

    # When
    _ = onboard_user(user=newcomer, template=template, actor_id="admin-a")

    # Then: 期限在 membership 粒度保留, 不会被最长或 permanent 折叠扩大。
    grant = AccessGrant.objects.get(user=newcomer, app=app, is_current=True)
    group_expiries = dict(
        AccessGrantGroup.objects.filter(grant=grant).values_list(
            "authorization_group__key",
            "expires_at",
        ),
    )
    short_expiry = group_expiries["sales"]
    long_expiry = group_expiries["long-term"]
    assert short_expiry is not None
    assert long_expiry is not None
    assert before + timedelta(days=29) < short_expiry < before + timedelta(days=31)
    assert before + timedelta(days=364) < long_expiry < before + timedelta(days=366)
    permission_link = AccessGrantPermission.objects.get(
        grant=grant,
        permission=permanent_permission,
    )
    assert permission_link.expires_at is None


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


def test_manual_handover_snapshot_uses_only_current_effective_grants() -> None:
    # Given: 当事人同时有当前有效、历史已撤销、以及状态尚未归档的已过期授权。
    current_app, current_group, _permission = _app_with_catalog("lc-current-app")
    revoked_app, revoked_group, _permission = _app_with_catalog("lc-old-revoked-app")
    expired_app, expired_group, _permission = _app_with_catalog("lc-old-expired-app")
    subject = _granted_user("lc-effective-only-user", current_app, current_group)
    revoked = GrantService.create_grant(
        GrantMutationInput(
            user=subject,
            app=revoked_app,
            authorization_groups=(AuthorizationGroupGrantInput(revoked_group, None),),
        ),
    )
    _ = GrantService.revoke_grant(
        user=subject,
        app=revoked_app,
        actor_type="system",
        actor_id="test",
    )
    expired = GrantService.create_grant(
        GrantMutationInput(
            user=subject,
            app=expired_app,
            authorization_groups=(
                AuthorizationGroupGrantInput(
                    expired_group,
                    timezone.now() + timedelta(days=1),
                ),
            ),
        ),
    )
    _ = AccessGrantGroup.objects.filter(
        grant=expired,
        authorization_group=expired_group,
    ).update(
        expires_at=timezone.now() - timedelta(seconds=1),
    )

    # When: 管理员手工建单, 未显式指定撤权前的授权 ID。
    task, _created = ensure_handover_task(
        subject=subject,
        kind="offboard",
        created_by="admin-a",
    )

    # Then: 仅快照当前有效授权, 不从历史行猜测。
    items = list(HandoverGrantItem.objects.filter(task=task))
    assert {item.app_id for item in items} == {current_app.id}
    assert revoked.id not in {item.source_grant_id for item in items}
    assert expired.id not in {item.source_grant_id for item in items}


def test_offboard_snapshot_uses_explicit_just_revoked_grant_ids_only() -> None:
    # Given: 本次目录离职撤销了一条授权, 当事人还有另一条更早的历史撤销授权。
    app, group, _permission = _app_with_catalog("lc-just-revoked-app")
    old_app, old_group, _permission = _app_with_catalog("lc-unrelated-history-app")
    subject = _granted_user("lc-explicit-revoked-user", app, group)
    just_revoked = AccessGrant.objects.get(user=subject, app=app, is_current=True)
    old_revoked = GrantService.create_grant(
        GrantMutationInput(
            user=subject,
            app=old_app,
            authorization_groups=(AuthorizationGroupGrantInput(old_group, None),),
        ),
    )
    _ = GrantService.revoke_grant(
        user=subject,
        app=old_app,
        actor_type="system",
        actor_id="earlier-sync",
    )
    _ = AuthentikSyncService.apply_directory_status(subject, USER_STATUS_DEPARTED)
    just_revoked.refresh_from_db()
    assert just_revoked.status == "revoked"

    # When: 离职编排显式传入本次刚撤销的 grant ID。
    result = start_offboarding(
        subject,
        snapshot_grant_ids=(just_revoked.id,),
    )

    # Then: 只快照显式授权, 不猜测其他历史行。
    items = list(HandoverGrantItem.objects.filter(task=result.task))
    assert {item.source_grant_id for item in items} == {just_revoked.id}
    assert old_revoked.id not in {item.source_grant_id for item in items}


def test_open_task_is_idempotent_for_same_kind() -> None:
    # Given
    app, group, _permission = _app_with_catalog("lc-unique-app")
    subject = _granted_user("lc-unique-user", app, group)
    first, _ = ensure_handover_task(subject=subject, kind="offboard", created_by="a")

    # When: 以同一 kind 重复建单。
    second, created = ensure_handover_task(subject=subject, kind="offboard", created_by="a")

    # Then: 幂等返回既有单。
    assert created is False
    assert second.id == first.id
    assert HandoverTask.objects.filter(subject_user=subject).count() == 1


def test_open_task_with_different_kind_conflicts() -> None:
    # Given: 当事人已有进行中的离职交接单。
    app, group, _permission = _app_with_catalog("lc-kind-conflict-app")
    subject = _granted_user("lc-kind-conflict-user", app, group)
    first, _created = ensure_handover_task(
        subject=subject,
        kind="offboard",
        created_by="a",
    )

    # When / Then: 转岗单不能将离职单当作幂等结果。
    with pytest.raises(lifecycle_services.HandoverConflictError):
        _ = ensure_handover_task(subject=subject, kind="transfer", created_by="a")
    assert HandoverTask.objects.filter(subject_user=subject).count() == 1
    assert HandoverTask.objects.get(subject_user=subject).id == first.id


def test_transfer_completion_clears_department_changed_flag() -> None:
    # Given: 被标记"部门已变更"的当事人 + 已确认差异的转岗单, 全部 APP 动作已收尾。
    app, group, _permission = _app_with_catalog("lc-clear-flag-app")
    subject = UserMirror.objects.create(
        authentik_user_id="lc-clear-flag-user",
        department="新部门",
        department_changed_at=timezone.now(),
    )
    _ = GrantService.create_grant(
        GrantMutationInput(
            user=subject,
            app=app,
            authorization_groups=(AuthorizationGroupGrantInput(group, None),),
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


def test_handover_without_actions_converges_to_completed() -> None:
    # Given: 当事人没有授权, 系统也没有声明交接 hook。
    subject = UserMirror.objects.create(authentik_user_id="lc-empty-actions-user")
    task, _created = ensure_handover_task(
        subject=subject,
        kind="offboard",
        created_by="admin-a",
    )
    assert not HandoverAppAction.objects.filter(task=task).exists()

    # When
    refreshed = lifecycle_services.refresh_task_status(task)

    # Then: 空 action 集合按真空收敛, 不会永久停在 pending。
    assert refreshed.status == "completed"


def test_handover_snapshot_names_and_keys_are_immutable_after_catalog_rename() -> None:
    # Given: 交接单已快照 App 与授权组的当时事实。
    app, group, _permission = _app_with_catalog("lc-snapshot-rename-app")
    subject = _granted_user("lc-snapshot-rename-user", app, group)
    task, _created = ensure_handover_task(
        subject=subject,
        kind="offboard",
        created_by="admin-a",
    )
    item = HandoverGrantItem.objects.get(task=task, app=app)
    action = HandoverAppAction.objects.get(task=task, app=app)
    assert item.app_key_snapshot == "lc-snapshot-rename-app"
    assert item.target_key_snapshot == "sales"

    # When: 目录中的 App 和授权组后续改名。
    _ = App.objects.filter(pk=app.pk).update(
        app_key="lc-snapshot-renamed-app",
        name="改名后应用",
    )
    _ = AuthorizationGroup.objects.filter(pk=group.pk).update(
        key="renamed-sales",
        name="改名后岗位",
    )

    # Then: 交接史料仍保留建单时的 key/name, 不受可变 FK 影响。
    item.refresh_from_db()
    action.refresh_from_db()
    assert item.app_key_snapshot == "lc-snapshot-rename-app"
    assert item.app_name_snapshot == "lc-snapshot-rename-app"
    assert item.target_kind_snapshot == "group"
    assert item.target_key_snapshot == "sales"
    assert item.target_name_snapshot == "销售"
    assert action.app_key_snapshot == "lc-snapshot-rename-app"
    assert action.app_name_snapshot == "lc-snapshot-rename-app"


def test_delete_task_only_after_cancelled_and_records_audit() -> None:
    # Given: 进行中的转岗单。
    app, group, _permission = _app_with_catalog("lc-delete-app")
    subject = UserMirror.objects.create(authentik_user_id="lc-delete-user")
    _ = GrantService.create_grant(
        GrantMutationInput(
            user=subject,
            app=app,
            authorization_groups=(AuthorizationGroupGrantInput(group, None),),
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
    subject = UserMirror.objects.create(authentik_user_id="local-admin:admin")

    # Then: 离职/转岗建单一律拒绝(误操作会禁掉 break-glass 入口)。
    with pytest.raises(HandoverConflictError):
        _ = ensure_handover_task(subject=subject, kind=HANDOVER_KIND_TRANSFER, created_by="a")
    with pytest.raises(HandoverConflictError):
        _ = start_offboarding(subject, created_by="admin-a")
