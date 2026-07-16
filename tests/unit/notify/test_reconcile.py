from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from easyauth.applications.models import App
from easyauth.notify.models import (
    CREDENTIAL_TYPE_STATIC_TOKEN,
    NOTIFY_ERROR_DINGTALK_DAILY_LIMIT,
    NOTIFY_ERROR_DINGTALK_DUPLICATE,
    NOTIFY_ERROR_DINGTALK_REJECTED,
    NOTIFY_MESSAGE_STATUS_COMPLETED,
    NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED,
    NOTIFY_MESSAGE_STATUS_SENDING,
    NOTIFY_RECIPIENT_STATUS_DELIVERED,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_SENT,
    NOTIFY_TEMPLATE_TEXT,
    NotifyMessage,
    NotifyRecipient,
)
from easyauth.notify.services import reconcile_send_results

pytestmark = pytest.mark.django_db


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
        template=NOTIFY_TEMPLATE_TEXT,
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


def _patch_reconcile_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    progress: dict[str, object],
    result: dict[str, object],
) -> None:
    client = MagicMock()
    client.get_send_progress.return_value = progress
    client.get_send_result.return_value = result

    def fake() -> tuple[MagicMock, int]:
        return client, 1001

    monkeypatch.setattr("easyauth.notify.services._dingtalk_client_and_agent", fake)


def test_reconcile_maps_four_list_types(monkeypatch: pytest.MonkeyPatch) -> None:
    message = _message_with_sent(
        app_key="notify-rc-map",
        userids=["ok1", "bad1", "dup1", "limit1"],
        task_id="task-map",
    )
    _patch_reconcile_client(
        monkeypatch,
        progress={"status": 2, "progress_in_percent": 100},
        result={
            "invalid_user_id_list": ["bad1"],
            "failed_user_id_list": [],
            "forbidden_list": [
                {"code": 143106, "count": 1, "userid": "dup1"},
                {"code": 143105, "count": 1, "userid": "limit1"},
            ],
            "read_user_id_list": ["ok1"],
            "unread_user_id_list": [],
        },
    )

    processed = reconcile_send_results()
    assert processed == 1

    by_uid = {
        row.dingtalk_userid: row
        for row in NotifyRecipient.objects.filter(message=message)
    }
    assert by_uid["ok1"].status == NOTIFY_RECIPIENT_STATUS_DELIVERED
    assert by_uid["bad1"].status == NOTIFY_RECIPIENT_STATUS_FAILED
    assert by_uid["bad1"].error_code == NOTIFY_ERROR_DINGTALK_REJECTED
    assert by_uid["dup1"].error_code == NOTIFY_ERROR_DINGTALK_DUPLICATE
    assert by_uid["limit1"].error_code == NOTIFY_ERROR_DINGTALK_DAILY_LIMIT

    message.refresh_from_db()
    assert message.status == NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED
    assert message.recipient_failed == 3  # noqa: PLR2004
    assert message.recipient_sent == 1


def test_reconcile_skips_incomplete_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    message = _message_with_sent(
        app_key="notify-rc-skip",
        userids=["u1"],
        task_id="task-skip",
    )
    _patch_reconcile_client(
        monkeypatch,
        progress={"status": 1, "progress_in_percent": 50},
        result={},
    )

    processed = reconcile_send_results()
    assert processed == 0
    row = NotifyRecipient.objects.get(message=message)
    assert row.status == NOTIFY_RECIPIENT_STATUS_SENT


def test_reconcile_stale_sent_optimistic_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = timezone.now() - timedelta(hours=25)
    message = _message_with_sent(
        app_key="notify-rc-stale",
        userids=["stale1"],
        task_id="task-stale",
        sent_at=stale,
    )
    # 不应调用钉钉(无窗口内 task)。
    client = MagicMock()

    def fake() -> tuple[MagicMock, int]:
        return client, 1001

    monkeypatch.setattr("easyauth.notify.services._dingtalk_client_and_agent", fake)

    _ = reconcile_send_results()

    row = NotifyRecipient.objects.get(message=message)
    assert row.status == NOTIFY_RECIPIENT_STATUS_DELIVERED
    message.refresh_from_db()
    assert message.status == NOTIFY_MESSAGE_STATUS_COMPLETED
    client.get_send_progress.assert_not_called()


def test_reconcile_disabled(settings: pytest.SettingsWrapper) -> None:
    settings.EASYAUTH_NOTIFY_RECONCILE_ENABLED = False
    _ = _message_with_sent(
        app_key="notify-rc-off",
        userids=["u1"],
        task_id="task-off",
    )
    assert reconcile_send_results() == 0
