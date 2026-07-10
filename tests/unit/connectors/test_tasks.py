from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.connectors import dispatch as dispatch_module
from easyauth.connectors.models import (
    SYNC_TRIGGER_MANUAL,
    SYNC_TRIGGER_OFFBOARD,
    ConnectorInstance,
    ConnectorSyncRun,
)
from easyauth.tasks import connectors as tasks_module
from easyauth.tasks.connectors import (
    offboard_user_task,
    prune_connector_sync_runs_task,
    schedule_connector_reconciles_task,
)
from tests.unit.connectors.fakes import FakeConnector

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.django_db

FAKE_CONNECTOR_PATH = "tests.unit.connectors.fakes.FakeConnector"


@pytest.fixture(autouse=True)
def register_fake_connector(settings: SettingsWrapper) -> None:
    settings.EASYAUTH_CONNECTORS = (FAKE_CONNECTOR_PATH,)
    FakeConnector.reset()


class _SendTaskRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def send_task(
        self,
        name: str,
        args: list[object] | None = None,
        kwargs: dict[str, object] | None = None,
        countdown: float | None = None,
    ) -> object:
        _ = (kwargs, countdown)
        self.calls.append((name, tuple(args or ())))
        return object()

    def enqueue_task(
        self,
        *,
        event_key: str,
        task_name: str,
        args: list[object] | tuple[object, ...] = (),
        kwargs: dict[str, object] | None = None,
        countdown: float = 0,
    ) -> object:
        _ = (event_key, kwargs, countdown)
        self.calls.append((task_name, tuple(args)))
        return object()


@pytest.fixture
def sent_tasks(monkeypatch: pytest.MonkeyPatch) -> _SendTaskRecorder:
    recorder = _SendTaskRecorder()
    monkeypatch.setattr(dispatch_module, "enqueue_task", recorder.enqueue_task)
    return recorder


def test_offboard_task_uses_same_serial_worker_as_reconcile(
    sent_tasks: _SendTaskRecorder,
) -> None:
    # Given
    app = App.objects.create(app_key="conn-task-off", name="X")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    user = UserMirror.objects.create(authentik_user_id="conn-task-off-u1")

    # When
    handled = offboard_user_task(user.authentik_user_id)

    # Then: 只推进持久 generation 并投递统一 worker, 不再旁路写外部系统。
    assert handled == 1
    assert FakeConnector.offboarded_user_ids == []
    assert not ConnectorSyncRun.objects.filter(instance=instance).exists()
    assert sent_tasks.calls == [
        ("easyauth.connectors.reconcile_instance", (instance.id,)),
    ]
    instance.refresh_from_db()
    assert instance.reconcile_generation == 1
    assert instance.reconcile_dirty is True
    assert instance.reconcile_pending_trigger == SYNC_TRIGGER_OFFBOARD


def test_offboard_during_active_lease_keeps_dirty_without_duplicate_worker(
    sent_tasks: _SendTaskRecorder,
) -> None:
    # Given: 连接器未实现快路径。
    app = App.objects.create(app_key="conn-task-fb", name="X")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    user = UserMirror.objects.create(authentik_user_id="conn-task-fb-u1")
    instance.reconcile_lease_token = UUID("b93264e2-69b3-4594-aa49-41af8cf3e32d")
    instance.reconcile_lease_expires_at = timezone.now() + timedelta(minutes=1)
    instance.save(
        update_fields=["reconcile_lease_token", "reconcile_lease_expires_at", "updated_at"]
    )

    # When
    handled = offboard_user_task(user.authentik_user_id)

    # Then: 回退为触发一次对账。
    assert handled == 1
    assert sent_tasks.calls == []
    instance.refresh_from_db()
    assert instance.reconcile_dirty is True
    assert instance.reconcile_pending_trigger == SYNC_TRIGGER_OFFBOARD


def test_scheduler_enqueues_due_instances_only(sent_tasks: _SendTaskRecorder) -> None:
    # Given: 一个到期(从未对账)、一个未到期、一个未启用。
    app = App.objects.create(app_key="conn-task-sched", name="X")
    due = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    fresh = ConnectorInstance.objects.create(
        app=App.objects.create(app_key="conn-task-sched-b", name="B"),
        connector_key="fake",
        enabled=True,
        last_reconcile_at=timezone.now(),
    )
    _ = fresh
    _ = ConnectorInstance.objects.create(
        app=App.objects.create(app_key="conn-task-sched-c", name="C"),
        connector_key="fake",
        enabled=False,
    )

    # When
    queued = schedule_connector_reconciles_task()

    # Then
    assert queued == 1
    assert sent_tasks.calls == [
        ("easyauth.connectors.reconcile_instance", (due.id,)),
    ]

    # 到期判定以实例自身 interval 为准。
    due.last_reconcile_at = timezone.now() - timedelta(seconds=due.reconcile_interval_seconds + 1)
    due.save(update_fields=["last_reconcile_at", "updated_at"])
    sent_tasks.calls.clear()
    # worker_queued 持久标记仍在(任务未真正执行), 不会重复投递; generation 仍推进。
    assert schedule_connector_reconciles_task() == 0


def test_scheduler_recovers_stale_broker_queue_independent_of_interval(
    sent_tasks: _SendTaskRecorder,
) -> None:
    now = timezone.now()
    app = App.objects.create(app_key="conn-task-recover", name="X")
    instance = ConnectorInstance.objects.create(
        app=app,
        connector_key="fake",
        enabled=True,
        last_reconcile_at=now,
        reconcile_interval_seconds=86400,
        reconcile_generation=1,
        reconcile_dirty=True,
        reconcile_worker_queued=True,
        reconcile_worker_queued_at=now - timedelta(minutes=11),
    )

    queued = schedule_connector_reconciles_task()

    assert queued == 1
    assert sent_tasks.calls == [
        ("easyauth.connectors.reconcile_instance", (instance.id,)),
    ]


def test_prune_keeps_recent_runs_per_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: 保留窗口收紧为 2 条, 现存 4 条。
    retention = 2
    total_runs = 4
    monkeypatch.setattr(tasks_module, "SYNC_RUN_RETENTION_PER_INSTANCE", retention)
    app = App.objects.create(app_key="conn-task-prune", name="X")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    base = timezone.now()
    for index in range(total_runs):
        _ = ConnectorSyncRun.objects.create(
            instance=instance,
            trigger=SYNC_TRIGGER_MANUAL,
            started_at=base - timedelta(minutes=index),
            finished_at=base - timedelta(minutes=index),
            status="success",
        )

    # When
    pruned = prune_connector_sync_runs_task()

    # Then: 只留最近 retention 条。
    assert pruned == total_runs - retention
    remaining = list(ConnectorSyncRun.objects.filter(instance=instance))
    assert len(remaining) == retention
    assert all(run.started_at >= base - timedelta(minutes=retention - 1) for run in remaining)
