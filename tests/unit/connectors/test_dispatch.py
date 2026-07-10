from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AuthorizationGroup
from easyauth.connectors import dispatch as dispatch_module
from easyauth.connectors.dispatch import (
    OFFBOARD_TASK_NAME,
    RECONCILE_TASK_NAME,
    dispatch_user_offboarded,
)
from easyauth.connectors.models import ConnectorInstance
from easyauth.grants.services import AuthorizationGroupGrantInput, GrantMutationInput, GrantService

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks

pytestmark = pytest.mark.django_db


@dataclass(slots=True)
class _SendTaskRecorder:
    calls: list[tuple[str, tuple[object, ...], float | None]] = field(default_factory=list)
    fail: bool = False

    def send_task(
        self,
        name: str,
        args: Sequence[object] | None = None,
        kwargs: dict[str, object] | None = None,
        countdown: float | None = None,
    ) -> object:
        _ = kwargs
        if self.fail:
            message = "broker unavailable"
            raise RuntimeError(message)
        self.calls.append((name, tuple(args or ()), countdown))
        return object()

    def enqueue_task(
        self,
        *,
        event_key: str,
        task_name: str,
        args: Sequence[object] = (),
        kwargs: dict[str, object] | None = None,
        countdown: float = 0,
    ) -> object:
        _ = (event_key, kwargs)
        self.calls.append((task_name, tuple(args), countdown or None))
        return object()


@pytest.fixture
def sent_tasks(monkeypatch: pytest.MonkeyPatch) -> _SendTaskRecorder:
    recorder = _SendTaskRecorder()
    monkeypatch.setattr(dispatch_module, "enqueue_task", recorder.enqueue_task)
    return recorder


def _grant_input(user: UserMirror, app: App) -> GrantMutationInput:
    group, _created = AuthorizationGroup.objects.get_or_create(
        app=app,
        key="connector-test",
        defaults={"kind": "bundle", "name": "Connector test"},
    )
    return GrantMutationInput(
        user=user,
        app=app,
        authorization_groups=(
            AuthorizationGroupGrantInput(authorization_group=group, expires_at=None),
        ),
        actor_type="user",
        actor_id="tester",
    )


def test_grant_mutation_enqueues_debounced_reconcile(
    sent_tasks: _SendTaskRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    # Given: 该 App 有启用的连接器实例。
    app = App.objects.create(app_key="conn-evt", name="X")
    user = UserMirror.objects.create(authentik_user_id="conn-evt-u1")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)

    # When: 授权事实变更(事务提交)。
    with django_capture_on_commit_callbacks(execute=True):
        _ = GrantService.create_grant(_grant_input(user, app))

    # Then: 以事件触发方式排队一次对账, 带去抖延迟。
    assert sent_tasks.calls == [
        (RECONCILE_TASK_NAME, (instance.id,), dispatch_module.RECONCILE_COALESCE_SECONDS),
    ]
    instance.refresh_from_db()
    assert instance.reconcile_generation == 1
    assert instance.reconcile_dirty is True


def test_grant_mutations_coalesce_within_debounce_window(
    sent_tasks: _SendTaskRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    # Given
    app = App.objects.create(app_key="conn-coalesce", name="X")
    user = UserMirror.objects.create(authentik_user_id="conn-coalesce-u1")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)

    # When: 去抖窗口内连续两次授权变更。
    with django_capture_on_commit_callbacks(execute=True):
        _ = GrantService.create_grant(_grant_input(user, app))
    with django_capture_on_commit_callbacks(execute=True):
        _ = GrantService.change_grant(_grant_input(user, app))

    # Then: 只投递一次 worker, 但两次事实变更都持久推进 generation。
    assert len(sent_tasks.calls) == 1
    instance.refresh_from_db()
    expected_generation = 2
    assert instance.reconcile_generation == expected_generation


def test_grant_mutation_without_enabled_instance_is_noop(
    sent_tasks: _SendTaskRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    # Given: 实例存在但未启用。
    app = App.objects.create(app_key="conn-disabled", name="X")
    user = UserMirror.objects.create(authentik_user_id="conn-disabled-u1")
    _ = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=False)

    # When
    with django_capture_on_commit_callbacks(execute=True):
        _ = GrantService.create_grant(_grant_input(user, app))

    # Then
    assert sent_tasks.calls == []


def test_dispatch_persists_dirty_and_queue_claim_without_contacting_broker(
    sent_tasks: _SendTaskRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    app = App.objects.create(app_key="conn-broker-fail", name="X")
    user = UserMirror.objects.create(authentik_user_id="conn-broker-fail-u1")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    with django_capture_on_commit_callbacks(execute=True):
        _ = GrantService.create_grant(_grant_input(user, app))

    instance.refresh_from_db()
    assert instance.reconcile_dirty is True
    assert instance.reconcile_worker_queued is True
    assert instance.reconcile_worker_queued_at is not None
    assert sent_tasks.calls == [
        (RECONCILE_TASK_NAME, (instance.id,), dispatch_module.RECONCILE_COALESCE_SECONDS),
    ]


def test_revoke_for_user_dispatches_per_app(
    sent_tasks: _SendTaskRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    # Given: 用户在两个接了连接器的 App 各有一条 current 授权。
    app_a = App.objects.create(app_key="conn-multi-a", name="A")
    app_b = App.objects.create(app_key="conn-multi-b", name="B")
    user = UserMirror.objects.create(authentik_user_id="conn-multi-u1")
    instance_a = ConnectorInstance.objects.create(app=app_a, connector_key="fake", enabled=True)
    instance_b = ConnectorInstance.objects.create(app=app_b, connector_key="fake", enabled=True)
    with django_capture_on_commit_callbacks(execute=True):
        _ = GrantService.create_grant(_grant_input(user, app_a))
        _ = GrantService.create_grant(_grant_input(user, app_b))
    sent_tasks.calls.clear()
    # 模拟已投递 worker 完成, 复位持久排队状态。
    ConnectorInstance.objects.filter(id__in=(instance_a.id, instance_b.id)).update(
        reconcile_dirty=False,
        reconcile_worker_queued=False,
    )

    # When: 全量撤销(离职撤权路径)。
    with django_capture_on_commit_callbacks(execute=True):
        _ = GrantService.revoke_for_user(
            user=user,
            reason="offboard",
            actor_type="system",
            actor_id="system",
        )

    # Then: 两个实例各排队一次对账。
    queued_instance_ids = {call[1][0] for call in sent_tasks.calls}
    assert queued_instance_ids == {instance_a.id, instance_b.id}


def test_dispatch_user_offboarded_enqueues_single_task(
    sent_tasks: _SendTaskRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    # Given: 存在启用实例。
    app = App.objects.create(app_key="conn-offboard", name="X")
    user = UserMirror.objects.create(authentik_user_id="conn-offboard-u1")
    _ = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)

    # When
    with django_capture_on_commit_callbacks(execute=True):
        dispatch_user_offboarded(user)

    # Then
    assert sent_tasks.calls == [(OFFBOARD_TASK_NAME, (user.authentik_user_id,), None)]


def test_dispatch_user_offboarded_without_enabled_instance_is_noop(
    sent_tasks: _SendTaskRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    # Given: 无任何启用实例。
    user = UserMirror.objects.create(authentik_user_id="conn-offboard-u2")

    # When
    with django_capture_on_commit_callbacks(execute=True):
        dispatch_user_offboarded(user)

    # Then
    assert sent_tasks.calls == []
