from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from django.core.cache import cache

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.connectors import dispatch as dispatch_module
from easyauth.connectors.dispatch import (
    OFFBOARD_TASK_NAME,
    RECONCILE_TASK_NAME,
    dispatch_user_offboarded,
)
from easyauth.connectors.models import ConnectorInstance
from easyauth.grants.services import GrantMutationInput, GrantService

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks

pytestmark = pytest.mark.django_db


@dataclass(slots=True)
class _SendTaskRecorder:
    calls: list[tuple[str, tuple[object, ...], float | None]] = field(default_factory=list)

    def send_task(
        self,
        name: str,
        args: Sequence[object] | None = None,
        kwargs: dict[str, object] | None = None,
        countdown: float | None = None,
    ) -> object:
        _ = kwargs
        self.calls.append((name, tuple(args or ()), countdown))
        return object()


@pytest.fixture
def sent_tasks(monkeypatch: pytest.MonkeyPatch) -> _SendTaskRecorder:
    recorder = _SendTaskRecorder()
    monkeypatch.setattr(dispatch_module, "current_app", recorder)
    return recorder


def _grant_input(user: UserMirror, app: App) -> GrantMutationInput:
    return GrantMutationInput(user=user, app=app, actor_type="user", actor_id="tester")


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
        (RECONCILE_TASK_NAME, (instance.id, "event"), dispatch_module.RECONCILE_COALESCE_SECONDS),
    ]


def test_grant_mutations_coalesce_within_debounce_window(
    sent_tasks: _SendTaskRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    # Given
    app = App.objects.create(app_key="conn-coalesce", name="X")
    user = UserMirror.objects.create(authentik_user_id="conn-coalesce-u1")
    _ = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)

    # When: 去抖窗口内连续两次授权变更。
    with django_capture_on_commit_callbacks(execute=True):
        _ = GrantService.create_grant(_grant_input(user, app))
    with django_capture_on_commit_callbacks(execute=True):
        _ = GrantService.change_grant(_grant_input(user, app))

    # Then: pending 标记合流, 只排一次任务。
    assert len(sent_tasks.calls) == 1


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
    # create 阶段留下的去抖 pending 标记会吞掉本次事件, 手工清缓存复位窗口。
    cache.clear()

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
