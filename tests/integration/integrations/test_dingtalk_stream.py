from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest
from dingtalk_stream import AckMessage, EventMessage
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog
from easyauth.integrations.authentik.directory_client import AuthentikDirectoryUnavailableError
from easyauth.integrations.authentik.directory_refresh import (
    DIRECTORY_REFRESH_MAX_RETRIES,
    REFRESH_MARKER_TTL_SECONDS,
    REFRESH_RETRY_BUDGET_SECONDS,
    REFRESH_WAIT_TIMEOUT_SECONDS,
    DirectoryRefreshHooks,
)
from easyauth.integrations.authentik.directory_sync_types import AuthentikDirectorySyncResult
from easyauth.integrations.dingtalk import stream as stream_module
from easyauth.integrations.dingtalk.api_client import DingTalkNotConfiguredError
from easyauth.integrations.dingtalk.stream import (
    STREAM_EVENT_CONFLICT_MESSAGE,
    EasyAuthDingTalkEventHandler,
    StreamEventIdentityError,
    build_stream_client,
    canonical_stream_data_sha256,
    record_stream_event,
)
from easyauth.integrations.models import (
    STREAM_EVENT_STATUS_FAILED,
    STREAM_EVENT_STATUS_PROCESSED,
    STREAM_EVENT_STATUS_SKIPPED,
    DingTalkStreamEvent,
)
from easyauth.outbox.models import OutboxEvent
from easyauth.tasks import dingtalk_stream as tasks_module
from easyauth.tasks.dingtalk_stream import (
    DIRECTORY_REFRESH_TASK_NAME,
    SKIP_REASON_INSTANCE_NOT_FOUND,
    SKIP_REASON_INSTANCE_STARTED,
    SKIP_REASON_RECORDED_NO_CONSUMER,
    SKIP_REASON_UNHANDLED_EVENT_TYPE,
    StreamEventContractError,
    process_dingtalk_stream_event_task,
    refresh_dingtalk_directory_task,
    request_directory_refresh,
)
from easyauth.tasks.dingtalk_stream_markers import (
    REFRESH_APPLY_BUDGET_SECONDS,
    REFRESH_COALESCE_SECONDS,
    REFRESH_MAX_CONSECUTIVE_REQUEUES,
    REFRESH_MIN_INTERVAL_SECONDS,
    REFRESH_RUNNING_CACHE_KEY_TEMPLATE,
    REFRESH_RUNNING_LOCK_TTL_SECONDS,
    REFRESH_TASK_SOFT_TIME_LIMIT_SECONDS,
    REFRESH_TASK_TIME_LIMIT_SECONDS,
    REFRESH_USER_IDS_CACHE_KEY_TEMPLATE,
    REFRESH_USER_IDS_MAX,
    acquire_running_lock,
    extend_running_lock,
)
from easyauth.workflows.models import (
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_CANCELED,
    APPROVAL_STATUS_SUBMITTED,
    ApprovalInstance,
    ApprovalTemplate,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks

pytestmark = pytest.mark.django_db


@dataclass(slots=True)
class _SendTaskRecorder:
    calls: list[tuple[str, tuple[object, ...], float | None]] = field(default_factory=list)
    task_kwargs: list[dict[str, object]] = field(default_factory=list)

    def send_task(
        self,
        name: str,
        args: Sequence[object] | None = None,
        kwargs: dict[str, object] | None = None,
        countdown: float | None = None,
    ) -> object:
        self.calls.append((name, tuple(args or ()), countdown))
        self.task_kwargs.append(dict(kwargs or {}))
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
        _ = event_key
        self.calls.append((task_name, tuple(args), countdown or None))
        self.task_kwargs.append(dict(kwargs or {}))
        return object()


@pytest.fixture
def sent_tasks(monkeypatch: pytest.MonkeyPatch) -> _SendTaskRecorder:
    recorder = _SendTaskRecorder()
    monkeypatch.setattr(tasks_module, "enqueue_task", recorder.enqueue_task)
    return recorder


@dataclass(slots=True)
class _RefreshRecorder:
    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    queued: bool = True

    def fake_refresh(
        self,
        _client: object,
        corp_id: str,
        **kwargs: object,
    ) -> AuthentikDirectorySyncResult | None:
        raw_ids = kwargs.get("user_ids", ())
        user_ids = tuple(cast("Sequence[str]", raw_ids))
        self.calls.append((corp_id, user_ids))
        if not self.queued:
            return None
        return AuthentikDirectorySyncResult(
            department_count=0,
            user_count=0,
            org_context_count=0,
            sync_state_count=0,
        )


@pytest.fixture
def refresh_recorder(monkeypatch: pytest.MonkeyPatch) -> _RefreshRecorder:
    recorder = _RefreshRecorder()
    monkeypatch.setattr(tasks_module, "refresh_dingtalk_directory", recorder.fake_refresh)
    monkeypatch.setattr(
        tasks_module.AuthentikDirectoryClient,
        "from_settings",
        lambda: object(),
    )
    return recorder


def test_record_stream_event_persists_and_enqueues_once(
    sent_tasks: _SendTaskRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    # Given/When: 同一 event_id 收到两次(钉钉重投)。
    with django_capture_on_commit_callbacks(execute=True):
        first = record_stream_event(
            event_id="evt-1",
            event_type="user_leave_org",
            corp_id="corp-1",
            born_time_ms=1751790000000,
            data={"userId": ["u-1"]},
        )
    with django_capture_on_commit_callbacks(execute=True):
        second = record_stream_event(
            event_id="evt-1",
            event_type="user_leave_org",
            corp_id="corp-1",
            born_time_ms=1751790000000,
            data={"userId": ["u-1"]},
        )

    # Then: 只落一行、只排一次处理任务, 幂等出口返回同一主键。
    event = DingTalkStreamEvent.objects.get(event_id="evt-1")
    assert first.created is True
    assert second.created is False
    assert first.event_pk == second.event_pk == _pk(event)
    assert event.born_at is not None
    outbox_event = OutboxEvent.objects.get(event_key="dingtalk-stream:evt-1")
    outbox_args = cast("list[object]", outbox_event.args)
    assert outbox_event.task_name == "easyauth.dingtalk_stream.process_event"
    assert outbox_args == [_pk(event)]
    assert sent_tasks.calls == []


def test_record_stream_event_detects_duplicate_after_raw_minimized(
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    # Given: 原始 data 已被 retention 最小化, 仅保留 canonical hash。
    with django_capture_on_commit_callbacks(execute=True):
        first = record_stream_event(
            event_id="evt-minimized-retry",
            event_type="user_leave_org",
            corp_id="corp-1",
            born_time_ms=1751790000000,
            data={"z": 1, "a": ["u-1"]},
        )
    event = DingTalkStreamEvent.objects.get(pk=first.event_pk)
    expected_hash = event.data_sha256
    event.data = {}
    event.data_minimized_at = timezone.now()
    event.save(update_fields=["data", "data_minimized_at", "updated_at"])

    # When: 钉钉重投同一事件, 字段顺序不同但 canonical data 相同。
    with django_capture_on_commit_callbacks(execute=True):
        second = record_stream_event(
            event_id="evt-minimized-retry",
            event_type="user_leave_org",
            corp_id="corp-1",
            born_time_ms=1751790000000,
            data={"a": ["u-1"], "z": 1},
        )

    # Then: 仍判定 duplicate, 不依赖 raw data。
    assert second.created is False
    assert second.event_pk == first.event_pk
    assert expected_hash == canonical_stream_data_sha256({"a": ["u-1"], "z": 1})
    assert DingTalkStreamEvent.objects.get(pk=first.event_pk).data_sha256 == expected_hash


def test_record_stream_event_conflict_fails_and_audits() -> None:
    _ = record_stream_event(
        event_id="evt-conflict",
        event_type="user_leave_org",
        corp_id="corp-1",
        born_time_ms=1751790000000,
        data={"userId": ["u-1"]},
    )

    with pytest.raises(ValueError, match=STREAM_EVENT_CONFLICT_MESSAGE):
        _ = record_stream_event(
            event_id="evt-conflict",
            event_type="user_add_org",
            corp_id="corp-1",
            born_time_ms=1751790000000,
            data={"userId": ["u-1"]},
        )

    audit = AuditLog.objects.get(event_type="dingtalk_stream_event_conflict")
    assert audit.target_id == "evt-conflict"
    assert audit.metadata["stored_event_type"] == "user_leave_org"
    assert audit.metadata["incoming_event_type"] == "user_add_org"


def test_record_stream_event_rejects_missing_identity(sent_tasks: _SendTaskRecorder) -> None:
    with pytest.raises(StreamEventIdentityError):
        _ = record_stream_event(
            event_id="",
            event_type="user_add_org",
            corp_id="corp-1",
            born_time_ms=None,
            data={},
        )
    assert not DingTalkStreamEvent.objects.exists()
    assert sent_tasks.calls == []


def test_database_rejects_stream_state_without_required_shape() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        _ = DingTalkStreamEvent.objects.create(
            event_id="evt-bad-processed",
            event_type="user_leave_org",
            status=STREAM_EVENT_STATUS_PROCESSED,
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        _ = DingTalkStreamEvent.objects.create(
            event_id="evt-bad-failed",
            event_type="user_leave_org",
            status=STREAM_EVENT_STATUS_FAILED,
        )


def test_build_stream_client_fails_fast_without_credentials() -> None:
    # 凭证未配置时常驻进程必须拒绝启动, 而不是空转假装在消费。
    with pytest.raises(DingTalkNotConfiguredError):
        _ = build_stream_client()


def test_handler_counts_stream_event_before_dedupe(monkeypatch: pytest.MonkeyPatch) -> None:
    keys: list[str] = []
    monkeypatch.setattr(
        stream_module,
        "record_usage",
        lambda key, *_args, **_kwargs: keys.append(str(key)),
        raising=False,
    )
    handler = EasyAuthDingTalkEventHandler()
    message = _event_message("evt-usage", "user_leave_org")
    _ = asyncio.run(handler.process(message))
    _ = asyncio.run(handler.process(message))
    assert keys == ["stream_event", "stream_event"]


def test_handler_acks_ok_and_marks_duplicate() -> None:
    # Given: 一条通讯录离职事件的 Stream 消息。
    message = _event_message("evt-ack", "user_leave_org")
    handler = EasyAuthDingTalkEventHandler()

    # When: 同一消息被推送两次。
    first_code, first_text = asyncio.run(handler.process(message))
    second_code, second_text = asyncio.run(handler.process(message))

    # Then: 两次都 ACK 成功, 第二次标记为重复; 收件箱只有一行。
    assert (first_code, first_text) == (AckMessage.STATUS_OK, "OK")
    assert (second_code, second_text) == (AckMessage.STATUS_OK, "duplicate")
    assert DingTalkStreamEvent.objects.filter(event_id="evt-ack").count() == 1


def test_handler_nacks_when_persist_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: 持久化必然失败(如数据库不可用)。
    def broken_record(**_kwargs: object) -> object:
        message = "db down"
        raise RuntimeError(message)

    monkeypatch.setattr(stream_module, "record_stream_event", broken_record)
    handler = EasyAuthDingTalkEventHandler()

    # When/Then: 返回系统异常让钉钉重投, 事件不会被 ACK 丢失。
    code, _text = asyncio.run(handler.process(_event_message("evt-broken", "user_add_org")))
    assert code == AckMessage.STATUS_SYSTEM_EXCEPTION


@pytest.mark.django_db(transaction=True)
def test_handler_nacks_conflicting_duplicate() -> None:
    _ = record_stream_event(
        event_id="evt-handler-conflict",
        event_type="user_add_org",
        corp_id="corp-1",
        born_time_ms=1751790000000,
        data={"corpId": "corp-1"},
    )
    handler = EasyAuthDingTalkEventHandler()

    code, text = asyncio.run(
        handler.process(_event_message("evt-handler-conflict", "user_leave_org"))
    )

    assert code == AckMessage.STATUS_SYSTEM_EXCEPTION
    assert text == "event persist failed"
    assert AuditLog.objects.filter(
        event_type="dingtalk_stream_event_conflict",
        target_id="evt-handler-conflict",
    ).exists()


def test_directory_event_queues_coalesced_refresh(
    sent_tasks: _SendTaskRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    # Given: 同一企业接连两条通讯录事件(入职+离职)。
    first = _stored_event("evt-dir-1", "user_add_org", data={"userId": ["u-new"]})
    second = _stored_event("evt-dir-2", "user_leave_org", data={"userId": ["u-gone"]})

    # When
    first_status = _process(first, django_capture_on_commit_callbacks)
    second_status = _process(second, django_capture_on_commit_callbacks)

    # Then: 两条都 processed, 但合并窗口内只排一次目录刷新任务。
    first.refresh_from_db()
    second.refresh_from_db()
    assert first_status == second_status == STREAM_EVENT_STATUS_PROCESSED
    assert first.result == {"corp_id": "corp-1", "refresh_queued": True, "user_ids": ["u-new"]}
    assert second.result == {"corp_id": "corp-1", "refresh_queued": False, "user_ids": ["u-gone"]}
    assert sent_tasks.calls == [
        (DIRECTORY_REFRESH_TASK_NAME, ("corp-1",), REFRESH_COALESCE_SECONDS)
    ]


def test_coalesced_user_events_send_deduplicated_user_ids(
    sent_tasks: _SendTaskRecorder,
    refresh_recorder: _RefreshRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    first = _stored_event(
        "evt-dir-ids-1",
        "user_add_org",
        data={"userId": ["u-new", "u-dup"]},
    )
    second = _stored_event(
        "evt-dir-ids-2",
        "user_leave_org",
        data={"userId": ["u-dup", "u-gone"]},
    )

    _ = _process(first, django_capture_on_commit_callbacks)
    _ = _process(second, django_capture_on_commit_callbacks)
    _ = refresh_dingtalk_directory_task("corp-1")

    assert sent_tasks.calls == [
        (DIRECTORY_REFRESH_TASK_NAME, ("corp-1",), REFRESH_COALESCE_SECONDS)
    ]
    assert refresh_recorder.calls == [("corp-1", ("u-new", "u-dup", "u-gone"))]


def test_department_only_burst_sends_empty_user_ids(
    sent_tasks: _SendTaskRecorder,
    refresh_recorder: _RefreshRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    first = _stored_event("evt-dept-1", "org_dept_create", data={"deptId": ["1"]})
    second = _stored_event("evt-dept-2", "org_dept_modify", data={"deptId": ["1"]})

    _ = _process(first, django_capture_on_commit_callbacks)
    _ = _process(second, django_capture_on_commit_callbacks)
    _ = refresh_dingtalk_directory_task("corp-1")

    assert sent_tasks.calls == [
        (DIRECTORY_REFRESH_TASK_NAME, ("corp-1",), REFRESH_COALESCE_SECONDS)
    ]
    assert refresh_recorder.calls == [("corp-1", ())]


def test_event_during_cooldown_schedules_one_trailing_with_merged_ids(
    sent_tasks: _SendTaskRecorder,
    refresh_recorder: _RefreshRecorder,
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    frozen = 1_700_000_000.0
    monkeypatch.setattr(tasks_module.time, "time", lambda: frozen)
    first = _stored_event("evt-cool-1", "user_add_org", data={"userId": ["u-1"]})
    _ = _process(first, django_capture_on_commit_callbacks)
    _ = refresh_dingtalk_directory_task("corp-1")

    during_a = _stored_event("evt-cool-2", "user_modify_org", data={"userId": ["u-2"]})
    during_b = _stored_event("evt-cool-3", "user_leave_org", data={"userId": ["u-3"]})
    _ = _process(during_a, django_capture_on_commit_callbacks)
    _ = _process(during_b, django_capture_on_commit_callbacks)
    _ = refresh_dingtalk_directory_task("corp-1")

    assert sent_tasks.calls == [
        (DIRECTORY_REFRESH_TASK_NAME, ("corp-1",), REFRESH_COALESCE_SECONDS),
        (DIRECTORY_REFRESH_TASK_NAME, ("corp-1",), REFRESH_MIN_INTERVAL_SECONDS),
    ]
    assert refresh_recorder.calls == [
        ("corp-1", ("u-1",)),
        ("corp-1", ("u-2", "u-3")),
    ]


def test_queued_false_keeps_ids_and_enqueues_one_delayed_followup(
    sent_tasks: _SendTaskRecorder,
    refresh_recorder: _RefreshRecorder,
    caplog: pytest.LogCaptureFixture,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    # 旧行为是触顶后只打日志并停住, id 会随 600 秒 TTL 消失。
    # 现在仍停掉忙等, 但恰好再排一次延迟补刷新, 倒计时等于整段重试预算。
    refresh_recorder.queued = False
    event = _stored_event("evt-nq-1", "user_add_org", data={"userId": ["u-hold"]})
    _ = _process(event, django_capture_on_commit_callbacks)

    for _attempt in range(REFRESH_MAX_CONSECUTIVE_REQUEUES):
        _ = refresh_dingtalk_directory_task("corp-1")

    assert len(sent_tasks.calls) == 1 + REFRESH_MAX_CONSECUTIVE_REQUEUES
    assert refresh_recorder.calls == [("corp-1", ("u-hold",))] * REFRESH_MAX_CONSECUTIVE_REQUEUES

    with caplog.at_level("ERROR", logger="easyauth.tasks.dingtalk_stream"):
        _ = refresh_dingtalk_directory_task("corp-1")
        _ = refresh_dingtalk_directory_task("corp-1")

    followups = [
        index
        for index, call in enumerate(sent_tasks.calls)
        if call[2] == float(REFRESH_RETRY_BUDGET_SECONDS)
    ]
    assert followups == [1 + REFRESH_MAX_CONSECUTIVE_REQUEUES]
    assert sent_tasks.task_kwargs[followups[0]] == {"trailing": True}
    assert refresh_recorder.calls == [("corp-1", ("u-hold",))] * (
        REFRESH_MAX_CONSECUTIVE_REQUEUES + 2
    )
    assert "已安排一次延迟补刷新" in caplog.text
    assert _pending_user_ids("corp-1") == ["u-hold"]

    later = _stored_event("evt-nq-2", "user_leave_org", data={"userId": ["u-later"]})
    _ = _process(later, django_capture_on_commit_callbacks)
    refresh_recorder.queued = True
    _ = refresh_dingtalk_directory_task("corp-1")
    assert refresh_recorder.calls[-1] == ("corp-1", ("u-hold", "u-later"))


def test_user_ids_overflow_keeps_first_200(
    sent_tasks: _SendTaskRecorder,
    refresh_recorder: _RefreshRecorder,
    caplog: pytest.LogCaptureFixture,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    overflow_ids = [f"u-{index:03d}" for index in range(REFRESH_USER_IDS_MAX + 1)]
    event = _stored_event("evt-overflow", "user_add_org", data={"userId": overflow_ids})

    with caplog.at_level("WARNING", logger="easyauth.tasks.dingtalk_stream_markers"):
        _ = _process(event, django_capture_on_commit_callbacks)
    _ = refresh_dingtalk_directory_task("corp-1")

    assert sent_tasks.calls == [
        (DIRECTORY_REFRESH_TASK_NAME, ("corp-1",), REFRESH_COALESCE_SECONDS)
    ]
    assert refresh_recorder.calls == [
        ("corp-1", tuple(overflow_ids[:REFRESH_USER_IDS_MAX])),
    ]
    assert "dropped=1" in caplog.text


def test_crash_redelivery_resends_the_same_peeked_ids(
    refresh_recorder: _RefreshRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _stored_event("evt-crash", "user_leave_org", data={"userId": ["u-crash"]})
    _ = _process(event, django_capture_on_commit_callbacks)

    def _crash(
        _client: object,
        corp_id: str,
        **kwargs: object,
    ) -> AuthentikDirectorySyncResult | None:
        raw_ids = kwargs.get("user_ids", ())
        user_ids = tuple(cast("Sequence[str]", raw_ids))
        refresh_recorder.calls.append((corp_id, user_ids))
        message = "worker killed"
        raise AuthentikDirectoryUnavailableError(message)

    monkeypatch.setattr(tasks_module, "refresh_dingtalk_directory", _crash)
    with pytest.raises(AuthentikDirectoryUnavailableError, match="worker killed"):
        _ = refresh_dingtalk_directory_task("corp-1")
    assert _pending_user_ids("corp-1") == ["u-crash"]

    monkeypatch.setattr(tasks_module, "refresh_dingtalk_directory", refresh_recorder.fake_refresh)
    _ = refresh_dingtalk_directory_task("corp-1")
    assert refresh_recorder.calls == [("corp-1", ("u-crash",)), ("corp-1", ("u-crash",))]


def test_ids_accumulated_during_inflight_survive_removal(
    sent_tasks: _SendTaskRecorder,
    refresh_recorder: _RefreshRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_during_trigger(
        _client: object,
        corp_id: str,
        **kwargs: object,
    ) -> AuthentikDirectorySyncResult | None:
        during = _stored_event("evt-mid", "user_leave_org", data={"userId": ["u-2"]})
        _ = _process(during, django_capture_on_commit_callbacks)
        return refresh_recorder.fake_refresh(_client, corp_id, **kwargs)

    monkeypatch.setattr(tasks_module, "refresh_dingtalk_directory", _fake_during_trigger)
    first = _stored_event("evt-mid-1", "user_leave_org", data={"userId": ["u-1"]})
    _ = _process(first, django_capture_on_commit_callbacks)
    _ = refresh_dingtalk_directory_task("corp-1")

    assert refresh_recorder.calls == [("corp-1", ("u-1",))]
    assert _pending_user_ids("corp-1") == ["u-2"]
    assert sent_tasks.calls[-1][0] == DIRECTORY_REFRESH_TASK_NAME

    monkeypatch.setattr(tasks_module, "refresh_dingtalk_directory", refresh_recorder.fake_refresh)
    _ = refresh_dingtalk_directory_task("corp-1")
    assert refresh_recorder.calls == [("corp-1", ("u-1",)), ("corp-1", ("u-2",))]


def test_event_during_running_refresh_arms_one_trailing_never_concurrent(
    sent_tasks: _SendTaskRecorder,
    refresh_recorder: _RefreshRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = 1_700_000_000.0
    monkeypatch.setattr(tasks_module.time, "time", lambda: frozen)

    def _fake_during_wait(
        _client: object,
        corp_id: str,
        **kwargs: object,
    ) -> AuthentikDirectorySyncResult | None:
        during = _stored_event("evt-run-2", "user_leave_org", data={"userId": ["u-2"]})
        _ = _process(during, django_capture_on_commit_callbacks)
        nested = refresh_dingtalk_directory_task(corp_id)
        assert all(value == 0 for value in nested.values())
        return refresh_recorder.fake_refresh(_client, corp_id, **kwargs)

    monkeypatch.setattr(tasks_module, "refresh_dingtalk_directory", _fake_during_wait)
    first = _stored_event("evt-run-1", "user_leave_org", data={"userId": ["u-1"]})
    _ = _process(first, django_capture_on_commit_callbacks)
    _ = refresh_dingtalk_directory_task("corp-1")

    assert refresh_recorder.calls == [("corp-1", ("u-1",))]
    trailing_calls = [
        call for call in sent_tasks.calls if call[0] == DIRECTORY_REFRESH_TASK_NAME
    ]
    assert len(trailing_calls) == 2
    assert trailing_calls[1][2] == REFRESH_MIN_INTERVAL_SECONDS

    monkeypatch.setattr(tasks_module, "refresh_dingtalk_directory", refresh_recorder.fake_refresh)
    _ = refresh_dingtalk_directory_task("corp-1")
    assert refresh_recorder.calls == [("corp-1", ("u-1",)), ("corp-1", ("u-2",))]


@pytest.mark.usefixtures("sent_tasks")
def test_rolled_back_transaction_leaves_no_blocking_marker(
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    def _enqueue_then_fail() -> None:
        with transaction.atomic():
            queued = request_directory_refresh(
                "corp-1",
                source_event_id="evt-rb",
                user_ids=("u-1",),
            )
            assert queued is True
            raise RuntimeError

    with pytest.raises(RuntimeError):
        _enqueue_then_fail()

    later = _stored_event("evt-after-rb", "user_leave_org", data={"userId": ["u-2"]})
    status = _process(later, django_capture_on_commit_callbacks)
    later.refresh_from_db()
    assert status == STREAM_EVENT_STATUS_PROCESSED
    assert later.result["refresh_queued"] is True


def test_directory_event_without_corp_marks_failed(sent_tasks: _SendTaskRecorder) -> None:
    event = _stored_event("evt-nocorp", "user_leave_org", corp_id="", data={})

    with pytest.raises(StreamEventContractError):
        _ = process_dingtalk_stream_event_task(_pk(event))

    event.refresh_from_db()
    assert event.status == STREAM_EVENT_STATUS_FAILED
    assert "corp_id" in event.error
    assert sent_tasks.calls == []


def test_processed_event_replay_has_no_side_effects(sent_tasks: _SendTaskRecorder) -> None:
    # Given: 已处理完成的事件(任务重复投递场景)。
    event = _stored_event("evt-replay", "user_leave_org", data={"userId": ["u-1"]})
    event.status = STREAM_EVENT_STATUS_PROCESSED
    event.processed_at = timezone.now()
    event.save(update_fields=["status", "processed_at"])

    # When/Then: 幂等出口直接返回, 不再触发目录刷新。
    assert process_dingtalk_stream_event_task(_pk(event)) == STREAM_EVENT_STATUS_PROCESSED
    assert sent_tasks.calls == []


def test_unhandled_event_type_is_skipped_and_kept(sent_tasks: _SendTaskRecorder) -> None:
    event = _stored_event("evt-hrm", "hrm_employee_dimission", data={"staffId": "u-1"})

    status = process_dingtalk_stream_event_task(_pk(event))

    event.refresh_from_db()
    assert status == STREAM_EVENT_STATUS_SKIPPED
    assert event.result == {"reason": SKIP_REASON_UNHANDLED_EVENT_TYPE}
    assert sent_tasks.calls == []


@pytest.mark.parametrize(
    "event_type",
    ["org_change", "label_user_change", "label_conf_add", "label_conf_del", "bpms_task_change"],
)
def test_record_only_event_types_are_caught(
    sent_tasks: _SendTaskRecorder,
    event_type: str,
) -> None:
    # 已订阅但暂无业务消费方的事件: 明确接住(落库+ACK), 不触发目录刷新。
    event = _stored_event(f"evt-{event_type}", event_type, data={"TimeStamp": "1751790000000"})

    status = process_dingtalk_stream_event_task(_pk(event))

    event.refresh_from_db()
    assert status == STREAM_EVENT_STATUS_SKIPPED
    assert event.result == {"reason": SKIP_REASON_RECORDED_NO_CONSUMER}
    assert sent_tasks.calls == []


def test_bpms_finish_agree_approves_instance() -> None:
    # Given: EasyAuth 发起的 submitted 审批实例。
    instance = _submitted_instance("stream-approve-app", "proc-stream-approve")
    event = _stored_event(
        "evt-bpms-agree",
        "bpms_instance_change",
        data={
            "processInstanceId": "proc-stream-approve",
            "type": "finish",
            "result": "agree",
        },
    )

    # When
    status = process_dingtalk_stream_event_task(_pk(event))

    # Then: 审批实例实时进入 approved, 事件回写实例线索。
    instance.refresh_from_db()
    event.refresh_from_db()
    assert status == STREAM_EVENT_STATUS_PROCESSED
    assert instance.status == APPROVAL_STATUS_APPROVED
    assert event.result["instance_id"] == str(instance.id)
    assert event.result["status"] == APPROVAL_STATUS_APPROVED


def test_bpms_terminate_cancels_instance() -> None:
    instance = _submitted_instance("stream-cancel-app", "proc-stream-cancel")
    event = _stored_event(
        "evt-bpms-terminate",
        "bpms_instance_change",
        data={"processInstanceId": "proc-stream-cancel", "type": "terminate"},
    )

    status = process_dingtalk_stream_event_task(_pk(event))

    instance.refresh_from_db()
    assert status == STREAM_EVENT_STATUS_PROCESSED
    assert instance.status == APPROVAL_STATUS_CANCELED


def test_bpms_start_event_is_skipped() -> None:
    instance = _submitted_instance("stream-start-app", "proc-stream-start")
    event = _stored_event(
        "evt-bpms-start",
        "bpms_instance_change",
        data={"processInstanceId": "proc-stream-start", "type": "start"},
    )

    status = process_dingtalk_stream_event_task(_pk(event))

    instance.refresh_from_db()
    event.refresh_from_db()
    assert status == STREAM_EVENT_STATUS_SKIPPED
    assert instance.status == APPROVAL_STATUS_SUBMITTED
    assert event.result["reason"] == SKIP_REASON_INSTANCE_STARTED


def test_bpms_unknown_instance_is_skipped() -> None:
    # Given: 企业内其他流程的审批事件(EasyAuth 没有对应实例)。
    event = _stored_event(
        "evt-bpms-foreign",
        "bpms_instance_change",
        data={"processInstanceId": "proc-not-ours", "type": "finish", "result": "agree"},
    )

    status = process_dingtalk_stream_event_task(_pk(event))

    event.refresh_from_db()
    assert status == STREAM_EVENT_STATUS_SKIPPED
    assert event.result["reason"] == SKIP_REASON_INSTANCE_NOT_FOUND


def test_bpms_unsupported_change_marks_failed() -> None:
    event = _stored_event(
        "evt-bpms-weird",
        "bpms_instance_change",
        data={"processInstanceId": "proc-weird", "type": "finish", "result": "unknown"},
    )

    with pytest.raises(StreamEventContractError):
        _ = process_dingtalk_stream_event_task(_pk(event))

    event.refresh_from_db()
    assert event.status == STREAM_EVENT_STATUS_FAILED


def test_running_lock_time_limits_stay_below_ttl() -> None:
    assert REFRESH_APPLY_BUDGET_SECONDS == 600
    assert (
        int(REFRESH_WAIT_TIMEOUT_SECONDS) + REFRESH_APPLY_BUDGET_SECONDS
    ) == REFRESH_RUNNING_LOCK_TTL_SECONDS
    assert refresh_dingtalk_directory_task.soft_time_limit == REFRESH_TASK_SOFT_TIME_LIMIT_SECONDS
    assert refresh_dingtalk_directory_task.time_limit == REFRESH_TASK_TIME_LIMIT_SECONDS
    assert (
        REFRESH_TASK_SOFT_TIME_LIMIT_SECONDS
        < REFRESH_TASK_TIME_LIMIT_SECONDS
        < REFRESH_RUNNING_LOCK_TTL_SECONDS
    )
    assert REFRESH_MARKER_TTL_SECONDS > REFRESH_RETRY_BUDGET_SECONDS > 600


def test_late_worker_does_not_delete_the_new_running_lock(
    refresh_recorder: _RefreshRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = REFRESH_RUNNING_CACHE_KEY_TEMPLATE.format(corp_id="corp-1")

    def _replace_lock(
        _client: object,
        corp_id: str,
        **kwargs: object,
    ) -> AuthentikDirectorySyncResult | None:
        hooks = kwargs["hooks"]
        assert isinstance(hooks, DirectoryRefreshHooks)
        assert cache.delete(key)
        assert cache.add(key, "token-b", timeout=REFRESH_RUNNING_LOCK_TTL_SECONDS)
        hooks.before_apply()
        return refresh_recorder.fake_refresh(_client, corp_id, **kwargs)

    monkeypatch.setattr(tasks_module, "refresh_dingtalk_directory", _replace_lock)
    event = _stored_event("evt-lock", "user_leave_org", data={"userId": ["u-lock"]})
    _ = _process(event, django_capture_on_commit_callbacks)
    with pytest.raises(RuntimeError, match="running 锁已不属于当前任务"):
        _ = refresh_dingtalk_directory_task("corp-1")
    assert cache.get(key) == "token-b"


def test_extend_running_lock_refreshes_expiry_for_the_same_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 1_800_000_000.0}
    monkeypatch.setattr(tasks_module.time, "time", lambda: clock["now"])
    token = acquire_running_lock("corp-1")
    assert token is not None
    clock["now"] += REFRESH_RUNNING_LOCK_TTL_SECONDS - 1
    extend_running_lock("corp-1", token)
    clock["now"] += 10
    key = REFRESH_RUNNING_CACHE_KEY_TEMPLATE.format(corp_id="corp-1")
    assert cache.get(key) == token
    clock["now"] += REFRESH_RUNNING_LOCK_TTL_SECONDS
    assert cache.get(key) is None


def test_user_ids_survive_outage_past_600_seconds(
    refresh_recorder: _RefreshRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"now": 1_700_000_000.0}
    monkeypatch.setattr(tasks_module.time, "time", lambda: clock["now"])
    gap = 700
    assert gap > 600
    assert gap < REFRESH_MARKER_TTL_SECONDS
    refresh_recorder.queued = False
    first = _stored_event("evt-long-1", "user_leave_org", data={"userId": ["u-old"]})
    _ = _process(first, django_capture_on_commit_callbacks)
    _ = refresh_dingtalk_directory_task("corp-1")

    clock["now"] += gap
    second = _stored_event("evt-long-2", "user_leave_org", data={"userId": ["u-new"]})
    _ = _process(second, django_capture_on_commit_callbacks)
    clock["now"] += gap
    assert _pending_user_ids("corp-1") == ["u-old", "u-new"]

    refresh_recorder.queued = True
    _ = refresh_dingtalk_directory_task("corp-1")
    assert refresh_recorder.calls[-1] == ("corp-1", ("u-old", "u-new"))


def test_celery_retry_exhaustion_enqueues_one_followup(
    sent_tasks: _SendTaskRecorder,
    refresh_recorder: _RefreshRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = refresh_recorder
    event = _stored_event("evt-exhaust", "user_leave_org", data={"userId": ["u-hold"]})
    _ = _process(event, django_capture_on_commit_callbacks)

    def _down(_client: object, _corp_id: str, **_kwargs: object) -> None:
        message = "upstream down"
        raise AuthentikDirectoryUnavailableError(message)

    monkeypatch.setattr(tasks_module, "refresh_dingtalk_directory", _down)
    refresh_dingtalk_directory_task.push_request(
        retries=DIRECTORY_REFRESH_MAX_RETRIES,
        called_directly=False,
    )
    try:
        with pytest.raises(AuthentikDirectoryUnavailableError, match="upstream down"):
            _ = refresh_dingtalk_directory_task("corp-1")
        with pytest.raises(AuthentikDirectoryUnavailableError, match="upstream down"):
            _ = refresh_dingtalk_directory_task("corp-1")
    finally:
        refresh_dingtalk_directory_task.pop_request()

    followups = [
        index
        for index, call in enumerate(sent_tasks.calls)
        if call[2] == float(REFRESH_RETRY_BUDGET_SECONDS)
    ]
    assert followups == [1]
    assert sent_tasks.task_kwargs[followups[0]] == {"trailing": True}
    assert _pending_user_ids("corp-1") == ["u-hold"]


def test_trailing_without_ids_or_dept_flag_skips_trigger(
    refresh_recorder: _RefreshRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    event = _stored_event("evt-trail-empty", "user_leave_org", data={"userId": ["u-1"]})
    _ = _process(event, django_capture_on_commit_callbacks)
    _ = refresh_dingtalk_directory_task("corp-1")
    _ = refresh_dingtalk_directory_task("corp-1", trailing=True)
    assert refresh_recorder.calls == [("corp-1", ("u-1",))]


def test_trailing_with_dept_flag_calls_trigger(
    sent_tasks: _SendTaskRecorder,
    refresh_recorder: _RefreshRecorder,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _during_refresh(
        _client: object,
        corp_id: str,
        **kwargs: object,
    ) -> AuthentikDirectorySyncResult | None:
        during = _stored_event("evt-dept-mid", "org_dept_modify", data={"deptId": ["1"]})
        _ = _process(during, django_capture_on_commit_callbacks)
        return refresh_recorder.fake_refresh(_client, corp_id, **kwargs)

    monkeypatch.setattr(tasks_module, "refresh_dingtalk_directory", _during_refresh)
    event = _stored_event("evt-trail-dept", "user_leave_org", data={"userId": ["u-1"]})
    _ = _process(event, django_capture_on_commit_callbacks)
    _ = refresh_dingtalk_directory_task("corp-1")
    assert sent_tasks.task_kwargs[-1] == {"trailing": True}

    monkeypatch.setattr(tasks_module, "refresh_dingtalk_directory", refresh_recorder.fake_refresh)
    _ = refresh_dingtalk_directory_task("corp-1", trailing=True)
    assert refresh_recorder.calls == [("corp-1", ("u-1",)), ("corp-1", ())]


def _pk(event: DingTalkStreamEvent) -> int:
    return cast("int", event.pk)


def _process(
    event: DingTalkStreamEvent,
    capture_on_commit: DjangoCaptureOnCommitCallbacks,
) -> str:
    with capture_on_commit(execute=True):
        return process_dingtalk_stream_event_task(_pk(event))


def _pending_user_ids(corp_id: str) -> list[str]:
    raw = cast("object", cache.get(REFRESH_USER_IDS_CACHE_KEY_TEMPLATE.format(corp_id=corp_id)))
    if raw is None:
        return []
    return list(cast("list[str]", raw))


def _event_message(event_id: str, event_type: str) -> EventMessage:
    message = EventMessage()
    message.headers.event_id = event_id
    message.headers.event_type = event_type
    message.headers.event_corp_id = "corp-1"
    message.headers.event_born_time = 1751790000000
    message.data = {"corpId": "corp-1"}
    return message


def _stored_event(
    event_id: str,
    event_type: str,
    *,
    corp_id: str = "corp-1",
    data: dict[str, object] | None = None,
) -> DingTalkStreamEvent:
    return DingTalkStreamEvent.objects.create(
        event_id=event_id,
        event_type=event_type,
        corp_id=corp_id,
        data=data or {},
    )


def _submitted_instance(app_key: str, process_instance_id: str) -> ApprovalInstance:
    app = App.objects.create(app_key=app_key, name=app_key)
    template = ApprovalTemplate.objects.create(
        app=app,
        key="expense",
        name="费用审批",
        dingtalk_process_code="PROC-TEST",
    )
    originator = UserMirror.objects.create(
        authentik_user_id=f"{app_key}-originator",
        dingtalk_source_slug="default",
        dingtalk_corp_id="corp-1",
        dingtalk_userid=f"{app_key}-dt",
    )
    return ApprovalInstance.objects.create(
        app=app,
        template=template,
        biz_key=f"{app_key}-biz-1",
        originator_user=originator,
        dingtalk_process_instance_id=process_instance_id,
        status=APPROVAL_STATUS_SUBMITTED,
        submission_state="submitted",
        payload_hash="0" * 64,
    )


def test_submitted_instance_fixture_keeps_complete_dingtalk_binding() -> None:
    instance = _submitted_instance("stream-binding-complete", "proc-binding-complete")

    originator = instance.originator_user
    assert originator.dingtalk_source_slug == "default"
    assert originator.dingtalk_corp_id == "corp-1"
    assert originator.dingtalk_userid == "stream-binding-complete-dt"


def test_dingtalk_user_partial_binding_remains_invalid() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        _ = UserMirror.objects.create(
            authentik_user_id="stream-binding-partial",
            dingtalk_userid="stream-binding-partial-dt",
        )
