from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest
from dingtalk_stream import AckMessage, EventMessage

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.integrations.dingtalk import stream as stream_module
from easyauth.integrations.dingtalk.api_client import DingTalkNotConfiguredError
from easyauth.integrations.dingtalk.stream import (
    EasyAuthDingTalkEventHandler,
    StreamEventIdentityError,
    build_stream_client,
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
    REFRESH_COALESCE_SECONDS,
    SKIP_REASON_INSTANCE_NOT_FOUND,
    SKIP_REASON_INSTANCE_STARTED,
    SKIP_REASON_RECORDED_NO_CONSUMER,
    SKIP_REASON_UNHANDLED_EVENT_TYPE,
    StreamEventContractError,
    process_dingtalk_stream_event_task,
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
    monkeypatch.setattr(tasks_module, "enqueue_task", recorder.enqueue_task)
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
    assert outbox_event.task_name == "easyauth.dingtalk_stream.process_event"
    assert outbox_event.args == [_pk(event)]
    assert sent_tasks.calls == []


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


def test_build_stream_client_fails_fast_without_credentials() -> None:
    # 凭证未配置时常驻进程必须拒绝启动, 而不是空转假装在消费。
    with pytest.raises(DingTalkNotConfiguredError):
        _ = build_stream_client()


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


def test_directory_event_queues_coalesced_refresh(sent_tasks: _SendTaskRecorder) -> None:
    # Given: 同一企业接连两条通讯录事件(入职+离职)。
    first = _stored_event("evt-dir-1", "user_add_org", data={"userId": ["u-new"]})
    second = _stored_event("evt-dir-2", "user_leave_org", data={"userId": ["u-gone"]})

    # When
    first_status = process_dingtalk_stream_event_task(_pk(first))
    second_status = process_dingtalk_stream_event_task(_pk(second))

    # Then: 两条都 processed, 但合并窗口内只排一次目录刷新任务。
    first.refresh_from_db()
    second.refresh_from_db()
    assert first_status == second_status == STREAM_EVENT_STATUS_PROCESSED
    assert first.result == {"corp_id": "corp-1", "refresh_queued": True, "user_ids": ["u-new"]}
    assert second.result == {"corp_id": "corp-1", "refresh_queued": False, "user_ids": ["u-gone"]}
    assert sent_tasks.calls == [
        (DIRECTORY_REFRESH_TASK_NAME, ("corp-1",), REFRESH_COALESCE_SECONDS)
    ]


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
    event.save(update_fields=["status"])

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


def _pk(event: DingTalkStreamEvent) -> int:
    return cast("int", event.pk)


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
