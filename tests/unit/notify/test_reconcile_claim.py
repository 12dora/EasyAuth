from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final, Protocol, cast

import pytest
from django.core.cache import cache

from easyauth.notify import reconciliation
from easyauth.notify.contracts import (
    NOTIFY_ERROR_DINGTALK_REJECTED,
    NOTIFY_RECONCILE_BACKOFF_SECONDS,
    NOTIFY_RECONCILE_MAX_ATTEMPTS,
)
from easyauth.notify.models import (
    NOTIFY_RECIPIENT_STATUS_DELIVERED,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_SENT,
    NotifyRecipient,
)
from easyauth.tasks.notify import (
    NOTIFY_RECONCILE_RUN_LOCK_KEY,
    reconcile_send_results_task,
)
from tests.unit.notify.test_reconcile import (
    _assert_attempt_recorded,
    _freeze,
    _message_with_sent,
    _patch_reconcile_client,
    _receipt_result,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("notification_channel_for_apps")]

APPLY_PATH: Final = "easyauth.notify.reconciliation._apply_send_result"
SELECT_PATH: Final = "easyauth.notify.reconciliation.select_reconcile_tasks"
TASK_RECONCILE_PATH: Final = "easyauth.tasks.notify.reconcile_send_results"

if TYPE_CHECKING:
    from uuid import UUID

    from easyauth.integrations.dingtalk.api_client import DingTalkSendResult


class _ApplySendResult(Protocol):
    def __call__(
        self,
        *,
        channel_id: int,
        task_id: str,
        send_result: DingTalkSendResult,
        now: datetime,
    ) -> set[UUID]:
        ...


def _channel_id(message_channel_id: int | None) -> int:
    assert isinstance(message_channel_id, int)
    return message_channel_id


def test_second_claim_skips_http_for_same_task(monkeypatch: pytest.MonkeyPatch) -> None:
    frozen = _freeze(monkeypatch)
    message = _message_with_sent(
        app_key="notify-rc-claim-race",
        userids=["u1"],
        task_id="task-claim-race",
        sent_at=frozen,
    )
    client = _patch_reconcile_client(
        monkeypatch,
        progress={"status": 2},
        result=_receipt_result(unread_user_id_list=["u1"]),
    )
    channel_id = _channel_id(message.channel_id)
    assert reconciliation.claim_reconcile_task(
        channel_id=channel_id,
        task_id="task-claim-race",
        now=frozen,
        pre_claim_attempts=0,
    )
    assert not reconciliation.claim_reconcile_task(
        channel_id=channel_id,
        task_id="task-claim-race",
        now=frozen,
        pre_claim_attempts=0,
    )

    def already_selected(_window_start: datetime, _now: datetime) -> list[tuple[int, str, int]]:
        return [(channel_id, "task-claim-race", 0)]

    monkeypatch.setattr(SELECT_PATH, already_selected)
    assert reconciliation.reconcile_send_results() == 0
    assert client.progress_calls == 0
    row = NotifyRecipient.objects.get(message=message)
    _assert_attempt_recorded(row, now=frozen, attempts=1)
    assert row.status == NOTIFY_RECIPIENT_STATUS_SENT


def test_apply_raise_records_claim_and_continues_tick(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    frozen = _freeze(monkeypatch)
    boom = _message_with_sent(
        app_key="notify-rc-apply-boom",
        userids=["boom-u"],
        task_id="task-apply-boom",
        sent_at=frozen,
    )
    ok = _message_with_sent(
        app_key="notify-rc-apply-ok",
        userids=["ok-u"],
        task_id="task-apply-ok",
        sent_at=frozen,
    )
    client = _patch_reconcile_client(
        monkeypatch,
        progress={"status": 2},
        result=_receipt_result(unread_user_id_list=["ok-u"]),
    )
    original_apply = cast("_ApplySendResult", vars(reconciliation)["_apply_send_result"])

    def apply_or_raise(
        *,
        channel_id: int,
        task_id: str,
        send_result: DingTalkSendResult,
        now: datetime,
    ) -> set[UUID]:
        if task_id == "task-apply-boom":
            raise RuntimeError
        return original_apply(
            channel_id=channel_id,
            task_id=task_id,
            send_result=send_result,
            now=now,
        )

    monkeypatch.setattr(APPLY_PATH, apply_or_raise)
    with caplog.at_level("ERROR", logger="easyauth.notify.reconciliation"):
        _ = reconciliation.reconcile_send_results()
    boom_row = NotifyRecipient.objects.get(message=boom)
    ok_row = NotifyRecipient.objects.get(message=ok)
    _assert_attempt_recorded(boom_row, now=frozen, attempts=1)
    _assert_attempt_recorded(ok_row, now=frozen, attempts=1)
    assert boom_row.status == NOTIFY_RECIPIENT_STATUS_SENT
    assert ok_row.status == NOTIFY_RECIPIENT_STATUS_DELIVERED
    assert any("task-apply-boom" in record.message for record in caplog.records)
    calls_after_first = client.progress_calls
    assert calls_after_first >= 2
    assert reconciliation.reconcile_send_results() == 0
    assert client.progress_calls == calls_after_first


def test_concurrent_claim_at_cap_never_raises_or_exceeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = _freeze(monkeypatch)
    message = _message_with_sent(
        app_key="notify-rc-claim-cap",
        userids=["u1"],
        task_id="task-claim-cap",
        sent_at=frozen,
    )
    _ = NotifyRecipient.objects.filter(message=message).update(
        reconcile_attempts=NOTIFY_RECONCILE_MAX_ATTEMPTS - 1,
    )
    channel_id = _channel_id(message.channel_id)
    assert reconciliation.claim_reconcile_task(
        channel_id=channel_id,
        task_id="task-claim-cap",
        now=frozen,
        pre_claim_attempts=NOTIFY_RECONCILE_MAX_ATTEMPTS - 1,
    )
    assert not reconciliation.claim_reconcile_task(
        channel_id=channel_id,
        task_id="task-claim-cap",
        now=frozen,
        pre_claim_attempts=NOTIFY_RECONCILE_MAX_ATTEMPTS - 1,
    )
    assert not reconciliation.claim_reconcile_task(
        channel_id=channel_id,
        task_id="task-claim-cap",
        now=frozen,
        pre_claim_attempts=99,
    )
    row = NotifyRecipient.objects.get(message=message)
    assert row.reconcile_attempts == NOTIFY_RECONCILE_MAX_ATTEMPTS
    last_step = NOTIFY_RECONCILE_BACKOFF_SECONDS[-1]
    assert row.next_reconcile_at == frozen + timedelta(seconds=last_step)


def test_out_of_range_pre_claim_clamps_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    frozen = _freeze(monkeypatch)
    message = _message_with_sent(
        app_key="notify-rc-claim-clamp",
        userids=["u1"],
        task_id="task-claim-clamp",
        sent_at=frozen,
    )
    channel_id = _channel_id(message.channel_id)
    assert reconciliation.claim_reconcile_task(
        channel_id=channel_id,
        task_id="task-claim-clamp",
        now=frozen,
        pre_claim_attempts=99,
    )
    row = NotifyRecipient.objects.get(message=message)
    assert row.reconcile_attempts == 1
    last_step = NOTIFY_RECONCILE_BACKOFF_SECONDS[-1]
    assert row.next_reconcile_at == frozen + timedelta(seconds=last_step)


def test_failed_rows_keep_receipt_error_after_cursor_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = _freeze(monkeypatch)
    message = _message_with_sent(
        app_key="notify-rc-keep-error",
        userids=["bad1", "pending1"],
        task_id="task-keep-error",
        sent_at=frozen,
    )
    _ = _patch_reconcile_client(
        monkeypatch,
        progress={"status": 2},
        result=_receipt_result(invalid_user_id_list=["bad1"]),
    )
    assert reconciliation.reconcile_send_results() == 1
    failed = NotifyRecipient.objects.get(message=message, dingtalk_userid="bad1")
    pending = NotifyRecipient.objects.get(message=message, dingtalk_userid="pending1")
    assert failed.status == NOTIFY_RECIPIENT_STATUS_FAILED
    assert failed.error_code == NOTIFY_ERROR_DINGTALK_REJECTED
    assert failed.error == "钉钉回执: 无效用户或发送失败。"
    assert pending.status == NOTIFY_RECIPIENT_STATUS_SENT
    assert pending.error == ""
    _assert_attempt_recorded(failed, now=frozen, attempts=1)
    _assert_attempt_recorded(pending, now=frozen, attempts=1)


def test_run_lock_prevents_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    frozen = _freeze(monkeypatch)
    message = _message_with_sent(
        app_key="notify-rc-run-lock",
        userids=["u1"],
        task_id="task-run-lock",
        sent_at=frozen,
    )
    client = _patch_reconcile_client(
        monkeypatch,
        progress={"status": 1},
        result=_receipt_result(),
    )
    assert cache.add(NOTIFY_RECONCILE_RUN_LOCK_KEY, "1", timeout=30)
    try:
        assert reconcile_send_results_task() == 0
        assert client.progress_calls == 0
        row = NotifyRecipient.objects.get(message=message)
        assert row.reconcile_attempts == 0
    finally:
        _ = cache.delete(NOTIFY_RECONCILE_RUN_LOCK_KEY)


def test_run_lock_released_after_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> int:
        raise RuntimeError

    monkeypatch.setattr(TASK_RECONCILE_PATH, boom)
    with pytest.raises(RuntimeError):
        _ = reconcile_send_results_task()
    assert cache.get(NOTIFY_RECONCILE_RUN_LOCK_KEY) is None

    def succeed() -> int:
        return 7

    monkeypatch.setattr(TASK_RECONCILE_PATH, succeed)
    assert reconcile_send_results_task() == 7
    assert cache.get(NOTIFY_RECONCILE_RUN_LOCK_KEY) is None
