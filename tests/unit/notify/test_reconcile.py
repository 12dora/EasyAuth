from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final, final

import pytest
from django.conf import settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from easyauth.applications.integration_settings import IntegrationSettings
from easyauth.applications.models import App, AppNotificationChannel
from easyauth.integrations.dingtalk.api_client import (
    DingTalkApiUnavailableError,
    DingTalkNotConfiguredError,
    DingTalkSendProgress,
    DingTalkSendResult,
)
from easyauth.integrations.dingtalk.work_notification import parse_send_progress, parse_send_result
from easyauth.notify.channel_config import dingtalk_client_and_agent
from easyauth.notify.contracts import (
    NOTIFY_RECONCILE_BACKOFF_SECONDS,
    NOTIFY_RECONCILE_CAP_REACHED_MESSAGE,
    NOTIFY_RECONCILE_MAX_ATTEMPTS,
    NOTIFY_RECONCILE_WINDOW_HOURS,
)
from easyauth.notify.models import (
    CREDENTIAL_TYPE_STATIC_TOKEN,
    NOTIFY_ERROR_DINGTALK_DAILY_LIMIT,
    NOTIFY_ERROR_DINGTALK_DUPLICATE,
    NOTIFY_ERROR_DINGTALK_REJECTED,
    NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED,
    NOTIFY_MESSAGE_STATUS_SENDING,
    NOTIFY_RECIPIENT_STATUS_DELIVERED,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_SENT,
    NotifyMessage,
    NotifyRecipient,
)
from easyauth.notify.reconciliation import reconcile_send_results, select_reconcile_tasks

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("notification_channel_for_apps")]
RECONCILE_DEPENDENCY_DOWN_MESSAGE: Final = "钉钉不可用"
UNEXPECTED_RESULT_CALL_MESSAGE: Final = "progress 失败后不应查询结果"
RECONCILE_NOW_PATH: Final = "easyauth.notify.reconciliation.timezone.now"
CLIENT_PATH: Final = "easyauth.notify.channel_config.dingtalk_client_and_agent"


@final
class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@final
class _FakeDingTalkClient:
    def __init__(self, *, progress: dict[str, object], result: dict[str, object]) -> None:
        self.progress = progress
        self.result = result
        self.progress_calls = 0
        self.progress_agent_ids: list[str | int] = []
        self.result_agent_ids: list[str | int] = []

    def get_send_progress(self, *, agent_id: str | int, task_id: str) -> DingTalkSendProgress:
        self.progress_agent_ids.append(agent_id)
        _ = task_id
        self.progress_calls += 1
        return parse_send_progress(self.progress)

    def get_send_result(self, *, agent_id: str | int, task_id: str) -> DingTalkSendResult:
        self.result_agent_ids.append(agent_id)
        _ = task_id
        return parse_send_result(self.result)


@final
class _FairnessDingTalkClient:
    def __init__(self) -> None:
        self.task_ids: list[str] = []

    def get_send_progress(self, *, agent_id: str | int, task_id: str) -> DingTalkSendProgress:
        _ = agent_id
        self.task_ids.append(task_id)
        progress: dict[str, object] = {"status": 2}
        return parse_send_progress(progress)

    def get_send_result(self, *, agent_id: str | int, task_id: str) -> DingTalkSendResult:
        _ = agent_id
        if task_id == "task-050":
            return parse_send_result(_receipt_result(invalid_user_id_list=["user-050"]))
        return parse_send_result(_receipt_result())


@final
class _AlwaysFailClient:
    def __init__(self) -> None:
        self.progress_calls = 0

    def get_send_progress(self, *, agent_id: str | int, task_id: str) -> DingTalkSendProgress:
        _ = (agent_id, task_id)
        self.progress_calls += 1
        raise DingTalkApiUnavailableError(RECONCILE_DEPENDENCY_DOWN_MESSAGE)

    def get_send_result(self, *, agent_id: str | int, task_id: str) -> DingTalkSendResult:
        _ = (agent_id, task_id)
        raise AssertionError(UNEXPECTED_RESULT_CALL_MESSAGE)


def _freeze(monkeypatch: pytest.MonkeyPatch, now: datetime | None = None) -> datetime:
    frozen = now if now is not None else timezone.now()

    def current() -> datetime:
        return frozen

    monkeypatch.setattr(RECONCILE_NOW_PATH, current)
    return frozen


def _message_with_sent(
    *,
    app_key: str,
    userids: list[str],
    task_id: str,
    sent_at: datetime | None = None,
) -> NotifyMessage:
    app = App.objects.create(app_key=app_key, name=app_key)
    now = sent_at if sent_at is not None else timezone.now()
    message = NotifyMessage.objects.create(
        app=app,
        channel=AppNotificationChannel.objects.get(app=app, is_active=True),
        title="测试通知",
        content="c",
        payload_hash="h" * 64,
        status=NOTIFY_MESSAGE_STATUS_SENDING,
        recipient_total=len(userids),
        recipient_sent=len(userids),
        recipient_failed=0,
        requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
        requested_credential_id=1,
    )
    for uid in userids:
        _ = NotifyRecipient.objects.create(
            message=message,
            raw_ref=f"dt:{uid}",
            dingtalk_userid=uid,
            status=NOTIFY_RECIPIENT_STATUS_SENT,
            dingtalk_task_id=task_id,
            sent_at=now,
        )
    return message


def _receipt_result(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "invalid_user_id_list": [],
        "failed_user_id_list": [],
        "forbidden_list": [],
        "read_user_id_list": [],
        "unread_user_id_list": [],
    }
    result.update(overrides)
    return result


def _patch_reconcile_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    progress: dict[str, object],
    result: dict[str, object],
) -> _FakeDingTalkClient:
    client = _FakeDingTalkClient(progress=progress, result=result)

    def fake(_channel: object) -> tuple[_FakeDingTalkClient, int]:
        return client, 1001

    monkeypatch.setattr(CLIENT_PATH, fake)
    return client


def _assert_attempt_recorded(row: NotifyRecipient, *, now: datetime, attempts: int) -> None:
    assert row.reconcile_attempts == attempts
    assert row.last_reconciled_at == now
    delay = NOTIFY_RECONCILE_BACKOFF_SECONDS[attempts - 1]
    assert row.next_reconcile_at == now + timedelta(seconds=delay)


def test_reconcile_maps_four_list_types(monkeypatch: pytest.MonkeyPatch) -> None:
    frozen = _freeze(monkeypatch)
    message = _message_with_sent(
        app_key="notify-rc-map",
        userids=["ok1", "bad1", "dup1", "limit1", "pending1"],
        task_id="task-map",
        sent_at=frozen,
    )
    client = _patch_reconcile_client(
        monkeypatch,
        progress={"status": 2, "progress_in_percent": 100},
        result=_receipt_result(
            invalid_dept_id_list=["dept-1"],
            invalid_user_id_list=["bad1"],
            forbidden_list=[
                {"code": 143106, "count": 1, "userid": "dup1"},
                {"code": 143105, "count": 1, "userid": "limit1"},
            ],
            unread_user_id_list=["ok1"],
        ),
    )
    assert reconcile_send_results() == 1
    assert client.progress_agent_ids == [1001]
    assert client.result_agent_ids == [1001]
    by_uid = {row.dingtalk_userid: row for row in NotifyRecipient.objects.filter(message=message)}
    assert by_uid["ok1"].status == NOTIFY_RECIPIENT_STATUS_DELIVERED
    assert by_uid["bad1"].status == NOTIFY_RECIPIENT_STATUS_FAILED
    assert by_uid["bad1"].error_code == NOTIFY_ERROR_DINGTALK_REJECTED
    assert by_uid["dup1"].error_code == NOTIFY_ERROR_DINGTALK_DUPLICATE
    assert by_uid["limit1"].error_code == NOTIFY_ERROR_DINGTALK_DAILY_LIMIT
    assert by_uid["pending1"].status == NOTIFY_RECIPIENT_STATUS_SENT
    _assert_attempt_recorded(by_uid["ok1"], now=frozen, attempts=1)
    message.refresh_from_db()
    assert message.status == NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED
    assert message.recipient_failed == 3
    assert message.recipient_sent == 2


def test_reconcile_skips_incomplete_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    frozen = _freeze(monkeypatch)
    message = _message_with_sent(
        app_key="notify-rc-skip",
        userids=["u1"],
        task_id="task-skip",
        sent_at=frozen,
    )
    client = _patch_reconcile_client(
        monkeypatch,
        progress={"status": 1, "progress_in_percent": 50},
        result=_receipt_result(),
    )
    assert reconcile_send_results() == 0
    row = NotifyRecipient.objects.get(message=message)
    assert row.status == NOTIFY_RECIPIENT_STATUS_SENT
    _assert_attempt_recorded(row, now=frozen, attempts=1)
    assert client.progress_calls == 1
    assert reconcile_send_results() == 0
    assert client.progress_calls == 1


@pytest.mark.parametrize(
    "kind",
    ["progress_pending", "result_applied", "contract_error", "unavailable", "unconfigured"],
)
def test_reconcile_every_outcome_records_attempt(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    frozen = _freeze(monkeypatch)
    message = _message_with_sent(
        app_key=f"notify-rc-outcome-{kind}",
        userids=["u1"],
        task_id=f"task-outcome-{kind}",
        sent_at=frozen,
    )
    if kind == "unavailable":

        def unavailable(_channel: object) -> tuple[_AlwaysFailClient, int]:
            return _AlwaysFailClient(), 1001

        monkeypatch.setattr(CLIENT_PATH, unavailable)
    elif kind == "unconfigured":

        def unconfigured(_channel: object) -> tuple[object, int]:
            raise DingTalkNotConfiguredError

        monkeypatch.setattr(CLIENT_PATH, unconfigured)
    else:
        progress = {"status": 1} if kind == "progress_pending" else {"status": 2}
        results: dict[str, dict[str, object]] = {
            "progress_pending": _receipt_result(),
            "result_applied": _receipt_result(unread_user_id_list=["u1"]),
            "contract_error": {"read_user_id_list": "not-a-list"},
        }
        _ = _patch_reconcile_client(monkeypatch, progress=progress, result=results[kind])
    _ = reconcile_send_results()
    row = NotifyRecipient.objects.get(message=message)
    _assert_attempt_recorded(row, now=frozen, attempts=1)
    if kind in {"contract_error", "unavailable", "unconfigured"}:
        assert row.error
    else:
        assert row.error == ""


def test_reconcile_contract_failure_advances_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    frozen = _freeze(monkeypatch)
    message = _message_with_sent(
        app_key="notify-rc-contract",
        userids=["not-classified"],
        task_id="task-contract",
        sent_at=frozen,
    )
    _ = _patch_reconcile_client(
        monkeypatch,
        progress={"status": 2},
        result={"read_user_id_list": "not-a-list", "unread_user_id_list": None},
    )
    assert reconcile_send_results() == 0
    row = NotifyRecipient.objects.get(message=message)
    assert row.status == NOTIFY_RECIPIENT_STATUS_SENT
    assert row.error
    _assert_attempt_recorded(row, now=frozen, attempts=1)


def test_reconcile_fairly_rotates_beyond_first_fifty_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key="notify-reconcile-fairness", name="Fairness")
    channel = AppNotificationChannel.objects.get(app=app, is_active=True)
    now = _freeze(monkeypatch)
    for index in range(51):
        message = NotifyMessage.objects.create(
            app=app,
            channel=channel,
            title="测试通知",
            content=f"message-{index:03d}",
            payload_hash=f"{index:064d}",
            status=NOTIFY_MESSAGE_STATUS_SENDING,
            recipient_total=1,
            recipient_sent=1,
            requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
            requested_credential_id=1,
        )
        _ = NotifyRecipient.objects.create(
            message=message,
            raw_ref=f"dt:user-{index:03d}",
            dingtalk_userid=f"user-{index:03d}",
            status=NOTIFY_RECIPIENT_STATUS_SENT,
            dingtalk_task_id=f"task-{index:03d}",
            sent_at=now,
        )
    window_start = now - timedelta(hours=NOTIFY_RECONCILE_WINDOW_HOURS)
    with CaptureQueriesContext(connection) as queries:
        selected = select_reconcile_tasks(window_start, now)
    assert len(queries) == 1
    assert len(selected) == 50
    assert (channel.id, "task-050") not in selected
    client = _FairnessDingTalkClient()

    def client_for_channel(
        _channel: AppNotificationChannel,
    ) -> tuple[_FairnessDingTalkClient, int]:
        return client, 1001

    monkeypatch.setattr(CLIENT_PATH, client_for_channel)
    assert reconcile_send_results() == 0
    assert "task-050" not in client.task_ids
    assert NotifyRecipient.objects.filter(last_reconciled_at__isnull=False).count() == 50
    client.task_ids.clear()
    assert reconcile_send_results() == 1
    assert client.task_ids[0] == "task-050"
    failed = NotifyRecipient.objects.get(dingtalk_task_id="task-050")
    assert failed.status == NOTIFY_RECIPIENT_STATUS_FAILED


def test_partial_failure_with_remaining_sent_updates_aggregate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = _message_with_sent(
        app_key="notify-partial-with-sent",
        userids=["failed-user", "still-sent-user"],
        task_id="task-partial-with-sent",
    )
    _ = _patch_reconcile_client(
        monkeypatch,
        progress={"status": 2},
        result=_receipt_result(invalid_user_id_list=["failed-user"]),
    )
    assert reconcile_send_results() == 1
    message.refresh_from_db()
    assert message.status == NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED
    still_sent = NotifyRecipient.objects.get(message=message, dingtalk_userid="still-sent-user")
    assert still_sent.status == NOTIFY_RECIPIENT_STATUS_SENT


def test_same_task_id_from_different_channels_does_not_cross_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _message_with_sent(
        app_key="notify-channel-task-first",
        userids=["first-user"],
        task_id="shared-task-id",
    )
    second = _message_with_sent(
        app_key="notify-channel-task-second",
        userids=["second-user"],
        task_id="shared-task-id",
    )
    first_client = _FakeDingTalkClient(
        progress={"status": 2},
        result=_receipt_result(invalid_user_id_list=["first-user"]),
    )
    second_client = _FakeDingTalkClient(progress={"status": 1}, result=_receipt_result())

    def client_for_channel(channel: AppNotificationChannel) -> tuple[_FakeDingTalkClient, int]:
        if channel.id == first.channel.id:
            return first_client, 1001
        return second_client, 1001

    monkeypatch.setattr(CLIENT_PATH, client_for_channel)
    assert reconcile_send_results() == 1
    assert NotifyRecipient.objects.get(message=first).status == NOTIFY_RECIPIENT_STATUS_FAILED
    assert NotifyRecipient.objects.get(message=second).status == NOTIFY_RECIPIENT_STATUS_SENT


def test_reconcile_stale_sent_remains_sent_without_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = timezone.now() - timedelta(hours=25)
    message = _message_with_sent(
        app_key="notify-rc-stale",
        userids=["stale1"],
        task_id="task-stale",
        sent_at=stale,
    )
    client = _patch_reconcile_client(monkeypatch, progress={"status": 2}, result={})
    _ = reconcile_send_results()
    row = NotifyRecipient.objects.get(message=message)
    assert row.status == NOTIFY_RECIPIENT_STATUS_SENT
    assert row.reconcile_attempts == 0
    message.refresh_from_db()
    assert message.status == NOTIFY_MESSAGE_STATUS_SENDING
    assert client.progress_calls == 0


def test_reconcile_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "EASYAUTH_NOTIFY_RECONCILE_ENABLED", False)
    _ = _message_with_sent(app_key="notify-rc-off", userids=["u1"], task_id="task-off")
    assert reconcile_send_results() == 0


def test_reconcile_dependency_failure_advances_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    frozen = _freeze(monkeypatch)
    message = _message_with_sent(
        app_key="notify-rc-dependency-failed",
        userids=["u1"],
        task_id="task-dependency-failed",
        sent_at=frozen,
    )
    def fake(_channel: object) -> tuple[_AlwaysFailClient, int]:
        return _AlwaysFailClient(), 1001

    monkeypatch.setattr(CLIENT_PATH, fake)
    assert reconcile_send_results() == 0
    row = NotifyRecipient.objects.get(message=message)
    assert row.error == RECONCILE_DEPENDENCY_DOWN_MESSAGE
    _assert_attempt_recorded(row, now=frozen, attempts=1)


def test_reconcile_backoff_steps_follow_attempt_index(monkeypatch: pytest.MonkeyPatch) -> None:
    start = timezone.now()
    clock = _Clock(start)
    monkeypatch.setattr(RECONCILE_NOW_PATH, clock)
    message = _message_with_sent(
        app_key="notify-rc-backoff",
        userids=["u1"],
        task_id="task-backoff",
        sent_at=start,
    )
    client = _patch_reconcile_client(monkeypatch, progress={"status": 1}, result=_receipt_result())
    assert reconcile_send_results() == 0
    row = NotifyRecipient.objects.get(message=message)
    _assert_attempt_recorded(row, now=start, attempts=1)
    clock.now = row.next_reconcile_at or start
    assert reconcile_send_results() == 0
    row.refresh_from_db()
    _assert_attempt_recorded(row, now=clock.now, attempts=2)
    assert client.progress_calls == 2


def test_reconcile_at_attempt_cap_is_never_selected_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = timezone.now()
    clock = _Clock(start)
    monkeypatch.setattr(RECONCILE_NOW_PATH, clock)
    message = _message_with_sent(
        app_key="notify-rc-cap",
        userids=["u1"],
        task_id="task-cap",
        sent_at=start,
    )
    client = _patch_reconcile_client(monkeypatch, progress={"status": 1}, result=_receipt_result())
    _ = NotifyRecipient.objects.filter(message=message).update(
        reconcile_attempts=NOTIFY_RECONCILE_MAX_ATTEMPTS - 1,
    )
    assert reconcile_send_results() == 0
    row = NotifyRecipient.objects.get(message=message)
    assert row.status == NOTIFY_RECIPIENT_STATUS_SENT
    assert row.error_code == ""
    assert row.error == NOTIFY_RECONCILE_CAP_REACHED_MESSAGE
    _assert_attempt_recorded(row, now=start, attempts=NOTIFY_RECONCILE_MAX_ATTEMPTS)
    assert client.progress_calls == 1
    clock.now = start + timedelta(seconds=NOTIFY_RECONCILE_BACKOFF_SECONDS[-1])
    assert reconcile_send_results() == 0
    assert client.progress_calls == 1


def test_reconcile_failing_client_stops_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = timezone.now()
    clock = _Clock(start)
    monkeypatch.setattr(RECONCILE_NOW_PATH, clock)
    message = _message_with_sent(
        app_key="notify-rc-max-fail",
        userids=["u1"],
        task_id="task-max-fail",
        sent_at=start,
    )
    client = _AlwaysFailClient()

    def fake(_channel: object) -> tuple[_AlwaysFailClient, int]:
        return client, 1001

    monkeypatch.setattr(CLIENT_PATH, fake)
    for hour in range(30):
        clock.now = start + timedelta(hours=hour)
        _ = reconcile_send_results()
    row = NotifyRecipient.objects.get(message=message)
    assert client.progress_calls == NOTIFY_RECONCILE_MAX_ATTEMPTS
    assert row.reconcile_attempts == NOTIFY_RECONCILE_MAX_ATTEMPTS
    assert row.status == NOTIFY_RECIPIENT_STATUS_SENT
    assert row.error == NOTIFY_RECONCILE_CAP_REACHED_MESSAGE


def test_reconcile_uses_notify_agent_id_not_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    settings_row = IntegrationSettings.load()
    settings_row.dingtalk_app_key = "main-key"
    settings_row.dingtalk_app_secret = "main-secret"
    settings_row.dingtalk_agent_id = "1001"
    settings_row.dingtalk_notify_app_key = "svc-key"
    settings_row.dingtalk_notify_app_secret = "svc-secret"
    settings_row.dingtalk_notify_agent_id = "9001"
    settings_row.save()
    message = _message_with_sent(app_key="notify-rc-agent", userids=["ok1"], task_id="task-agent")
    assert message.channel.agent_id == "1001"
    captured: list[tuple[str, str | int]] = []

    class RecordingClient:
        def get_send_progress(self, *, agent_id: str | int, task_id: str) -> DingTalkSendProgress:
            captured.append(("progress", agent_id))
            _ = task_id
            progress: dict[str, object] = {"status": 2, "progress_in_percent": 100}
            return parse_send_progress(progress)

        def get_send_result(self, *, agent_id: str | int, task_id: str) -> DingTalkSendResult:
            captured.append(("result", agent_id))
            _ = task_id
            return parse_send_result(_receipt_result(read_user_id_list=["ok1"]))

    def fake(bound_channel: AppNotificationChannel) -> tuple[RecordingClient, str | int]:
        _client, agent_id = dingtalk_client_and_agent(bound_channel)
        return RecordingClient(), agent_id

    monkeypatch.setattr(CLIENT_PATH, fake)
    assert reconcile_send_results() == 1
    assert captured == [("progress", 9001), ("result", 9001)]
