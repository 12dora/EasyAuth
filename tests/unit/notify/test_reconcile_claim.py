from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Final, Protocol, cast, final

import pytest
from django.core.cache import cache
from django.utils import timezone

from easyauth.integrations.dingtalk.work_notification import parse_send_progress
from easyauth.notify import reconciliation
from easyauth.notify.contracts import (
    NOTIFY_ERROR_DINGTALK_REJECTED,
    NOTIFY_RECONCILE_BACKOFF_SECONDS,
    NOTIFY_RECONCILE_MAX_ATTEMPTS,
    NOTIFY_RECONCILE_TASK_LIMIT,
)
from easyauth.notify.models import (
    NOTIFY_RECIPIENT_STATUS_DELIVERED,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_SENT,
    NotifyRecipient,
)
from easyauth.tasks.notify import (
    NOTIFY_RECONCILE_RUN_LOCK_KEY,
    NOTIFY_RECONCILE_RUN_LOCK_TTL_SECONDS,
    reconcile_send_results_task,
)
from tests.unit.notify.test_reconcile import (
    CLIENT_PATH,
    RECONCILE_NOW_PATH,
    _assert_attempt_recorded,
    _Clock,
    _freeze,
    _message_with_sent,
    _patch_reconcile_client,
    _receipt_result,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("notification_channel_for_apps")]

APPLY_PATH: Final = "easyauth.notify.reconciliation._apply_send_result"
SELECT_PATH: Final = "easyauth.notify.reconciliation.select_reconcile_tasks"
TASK_RECONCILE_PATH: Final = "easyauth.tasks.notify.reconcile_send_results"
_RESULT_BEFORE_DONE: Final = "进度未完成不应查询结果。"
_SLOW_ROUND_GAP_SECONDS: Final = 5
_LOCK_HEADROOM_SECONDS: Final = 120

if TYPE_CHECKING:
    from uuid import UUID

    from easyauth.integrations.dingtalk.api_client import DingTalkSendProgress, DingTalkSendResult


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


@final
class _BatchThenClaimClock:
    def __init__(self, batch_start: datetime, claim_at: datetime) -> None:
        self.batch_start = batch_start
        self.claim_at = claim_at
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        if self.calls == 1:
            return self.batch_start
        return self.claim_at


@final
class _AdvancingClient:
    def __init__(self, clock: _Clock, *, jump_seconds: int) -> None:
        self.clock = clock
        self.jump_seconds = jump_seconds
        self.task_ids: list[str] = []

    def get_send_progress(self, *, agent_id: str | int, task_id: str) -> DingTalkSendProgress:
        _ = agent_id
        self.task_ids.append(task_id)
        self.clock.now += timedelta(seconds=self.jump_seconds)
        return parse_send_progress({"status": 1})

    def get_send_result(self, *, agent_id: str | int, task_id: str) -> DingTalkSendResult:
        _ = (agent_id, task_id)
        raise AssertionError(_RESULT_BEFORE_DONE)


def _seed_open_tasks(*, count: int, prefix: str, sent_at: datetime) -> None:
    for index in range(count):
        _ = _message_with_sent(
            app_key=f"notify-rc-{prefix}-{index:03d}",
            userids=[f"{prefix}-u-{index:03d}"],
            task_id=f"{prefix}-{index:03d}",
            sent_at=sent_at,
        )


def _install_client(monkeypatch: pytest.MonkeyPatch, client: _AdvancingClient) -> None:
    def fake(_channel: object) -> tuple[_AdvancingClient, int]:
        return client, 1001

    monkeypatch.setattr(CLIENT_PATH, fake)


def _assert_spaced_claim_stamps(
    *,
    prefix: str,
    start: datetime,
    gap_seconds: int,
    count: int,
) -> None:
    step = timedelta(seconds=NOTIFY_RECONCILE_BACKOFF_SECONDS[0])
    for index in range(count):
        row = NotifyRecipient.objects.get(dingtalk_task_id=f"{prefix}-{index:03d}")
        claim_at = start + timedelta(seconds=gap_seconds * index)
        assert row.reconcile_attempts == 1
        assert row.last_reconciled_at == claim_at
        assert row.next_reconcile_at is not None
        assert row.next_reconcile_at >= claim_at + step


def _assert_unclaimed(*, prefix: str, indexes: tuple[int, ...]) -> None:
    for index in indexes:
        row = NotifyRecipient.objects.get(dingtalk_task_id=f"{prefix}-{index:03d}")
        assert row.reconcile_attempts == 0
        assert row.last_reconciled_at is None
        assert row.next_reconcile_at is None


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
        eligible_at=frozen,
        claimed_at=frozen,
        pre_claim_attempts=0,
    )
    assert not reconciliation.claim_reconcile_task(
        channel_id=channel_id,
        task_id="task-claim-race",
        eligible_at=frozen,
        claimed_at=frozen,
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
        eligible_at=frozen,
        claimed_at=frozen,
        pre_claim_attempts=NOTIFY_RECONCILE_MAX_ATTEMPTS - 1,
    )
    assert not reconciliation.claim_reconcile_task(
        channel_id=channel_id,
        task_id="task-claim-cap",
        eligible_at=frozen,
        claimed_at=frozen,
        pre_claim_attempts=NOTIFY_RECONCILE_MAX_ATTEMPTS - 1,
    )
    assert not reconciliation.claim_reconcile_task(
        channel_id=channel_id,
        task_id="task-claim-cap",
        eligible_at=frozen,
        claimed_at=frozen,
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
        eligible_at=frozen,
        claimed_at=frozen,
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
    def boom(*, tick_budget_seconds: int) -> int:
        _ = tick_budget_seconds
        raise RuntimeError

    monkeypatch.setattr(TASK_RECONCILE_PATH, boom)
    with pytest.raises(RuntimeError):
        _ = reconcile_send_results_task()
    assert cache.get(NOTIFY_RECONCILE_RUN_LOCK_KEY) is None

    def succeed(*, tick_budget_seconds: int) -> int:
        _ = tick_budget_seconds
        return 7

    monkeypatch.setattr(TASK_RECONCILE_PATH, succeed)
    assert reconcile_send_results_task() == 7
    assert cache.get(NOTIFY_RECONCILE_RUN_LOCK_KEY) is None


def test_slow_round_stamps_next_reconcile_from_claim_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    count = NOTIFY_RECONCILE_TASK_LIMIT
    gap_seconds = _SLOW_ROUND_GAP_SECONDS
    budget = reconciliation.NOTIFY_RECONCILE_TICK_BUDGET_SECONDS
    assert gap_seconds * (count - 1) < budget
    start = timezone.now()
    prefix = "slow-claim"
    _seed_open_tasks(count=count, prefix=prefix, sent_at=start)
    clock = _Clock(start)
    monkeypatch.setattr(RECONCILE_NOW_PATH, clock)
    client = _AdvancingClient(clock, jump_seconds=gap_seconds)
    _install_client(monkeypatch, client)
    _ = reconciliation.reconcile_send_results()
    assert client.task_ids == [f"{prefix}-{index:03d}" for index in range(count)]
    _assert_spaced_claim_stamps(
        prefix=prefix,
        start=start,
        gap_seconds=gap_seconds,
        count=count,
    )


def test_tick_budget_stops_claiming_remaining_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    budget = reconciliation.NOTIFY_RECONCILE_TICK_BUDGET_SECONDS
    assert NOTIFY_RECONCILE_RUN_LOCK_TTL_SECONDS - budget >= _LOCK_HEADROOM_SECONDS
    start = timezone.now()
    prefix = "tick-budget"
    _seed_open_tasks(count=3, prefix=prefix, sent_at=start)
    clock = _Clock(start)
    monkeypatch.setattr(RECONCILE_NOW_PATH, clock)
    client = _AdvancingClient(clock, jump_seconds=budget)
    _install_client(monkeypatch, client)
    _ = reconciliation.reconcile_send_results()
    assert client.task_ids == [f"{prefix}-000"]
    claimed = NotifyRecipient.objects.get(dingtalk_task_id=f"{prefix}-000")
    _assert_attempt_recorded(claimed, now=start, attempts=1)
    _assert_unclaimed(prefix=prefix, indexes=(1, 2))


def test_claim_eligibility_uses_batch_start_time(monkeypatch: pytest.MonkeyPatch) -> None:
    batch_start = timezone.now()
    claim_at = batch_start + timedelta(seconds=90)
    later_at = batch_start + timedelta(seconds=30)
    message = _message_with_sent(
        app_key="notify-rc-eligible-batch",
        userids=["due-user", "later-user"],
        task_id="task-eligible-batch",
        sent_at=batch_start,
    )
    future = _message_with_sent(
        app_key="notify-rc-eligible-future",
        userids=["future-user"],
        task_id="task-eligible-future",
        sent_at=batch_start,
    )
    _ = NotifyRecipient.objects.filter(message=message, dingtalk_userid="due-user").update(
        next_reconcile_at=batch_start,
    )
    _ = NotifyRecipient.objects.filter(message=message, dingtalk_userid="later-user").update(
        next_reconcile_at=later_at,
    )
    _ = NotifyRecipient.objects.filter(message=future).update(next_reconcile_at=later_at)
    monkeypatch.setattr(RECONCILE_NOW_PATH, _BatchThenClaimClock(batch_start, claim_at))
    client = _patch_reconcile_client(
        monkeypatch,
        progress={"status": 1},
        result=_receipt_result(),
    )
    _ = reconciliation.reconcile_send_results()
    due = NotifyRecipient.objects.get(message=message, dingtalk_userid="due-user")
    later = NotifyRecipient.objects.get(message=message, dingtalk_userid="later-user")
    future_row = NotifyRecipient.objects.get(message=future)
    _assert_attempt_recorded(due, now=claim_at, attempts=1)
    assert later.reconcile_attempts == 0
    assert later.last_reconciled_at is None
    assert later.next_reconcile_at == later_at
    assert future_row.reconcile_attempts == 0
    assert future_row.last_reconciled_at is None
    assert future_row.next_reconcile_at == later_at
    assert client.progress_calls == 1
