from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from easyauth.accounts.models import DingTalkUserMirror, UserMirror
from easyauth.applications.models import App, AppNotificationChannel
from easyauth.integrations.dingtalk.api_client import (
    DingTalkApiRequestError,
    DingTalkApiUnavailableError,
)
from easyauth.notify.models import (
    CREDENTIAL_TYPE_STATIC_TOKEN,
    NOTIFY_ERROR_DINGTALK_REJECTED,
    NOTIFY_ERROR_EXHAUSTED,
    NOTIFY_MESSAGE_STATUS_COMPLETED,
    NOTIFY_MESSAGE_STATUS_FAILED,
    NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED,
    NOTIFY_MESSAGE_STATUS_PENDING,
    NOTIFY_MESSAGE_STATUS_SENDING,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_PENDING,
    NOTIFY_RECIPIENT_STATUS_SENT,
    NOTIFY_RECIPIENT_STATUS_THROTTLED,
    NOTIFY_TEMPLATE_TEXT,
    NotifyMessage,
    NotifyRecipient,
)
from easyauth.notify.services import (
    MAX_DELIVERY_ATTEMPTS,
    NOTIFY_THROTTLE_RETRY_SECONDS,
    accept_notify_message,
    deliver_message,
)
from easyauth.outbox.models import OutboxEvent

pytestmark = pytest.mark.django_db

CORP_ID = "corp-delivery"
SOURCE = "dingtalk-primary"


def _seed_user(*, authentik: str, dingtalk: str) -> None:
    _ = DingTalkUserMirror.objects.create(
        source_slug=SOURCE,
        corp_id=CORP_ID,
        user_id=dingtalk,
        name=dingtalk,
        status="active",
    )
    _ = UserMirror.objects.create(
        authentik_user_id=authentik,
        dingtalk_userid=dingtalk,
        dingtalk_corp_id=CORP_ID,
    )


def _accept(app: App, recipients: list[str]) -> NotifyMessage:
    result = accept_notify_message(
        app=app,
        recipients=recipients,
        template=NOTIFY_TEMPLATE_TEXT,
        content=f"body-{recipients[0]}",
        requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
        requested_credential_id=1,
    )
    return result.message


def _patch_dingtalk(
    monkeypatch: pytest.MonkeyPatch,
    *,
    send_side_effect: object | None = None,
    task_ids: list[str] | None = None,
) -> MagicMock:
    client = MagicMock()
    if send_side_effect is not None:
        client.send_work_notification.side_effect = send_side_effect
    elif task_ids is not None:
        client.send_work_notification.side_effect = list(task_ids)
    else:
        client.send_work_notification.return_value = "task-1"

    def fake_client_and_agent(_channel: object) -> tuple[MagicMock, int]:
        return client, 1001

    monkeypatch.setattr(
        "easyauth.notify.services._dingtalk_client_and_agent",
        fake_client_and_agent,
    )
    return client


def test_deliver_all_success_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.objects.create(app_key="notify-sm-ok", name="OK")
    _seed_user(authentik="u1", dingtalk="dt1")
    _seed_user(authentik="u2", dingtalk="dt2")
    message = _accept(app, ["u1", "u2"])
    _patch_dingtalk(monkeypatch, task_ids=["t-ok"])

    deliver_message(str(message.id), 1)

    message.refresh_from_db()
    assert message.status == NOTIFY_MESSAGE_STATUS_COMPLETED
    assert message.recipient_sent == 2  # noqa: PLR2004
    assert message.recipient_failed == 0
    assert message.claim_token == ""
    assert message.completed_at is not None
    assert NotifyRecipient.objects.filter(
        message=message,
        status=NOTIFY_RECIPIENT_STATUS_SENT,
    ).count() == 2  # noqa: PLR2004


def test_delivery_uses_channel_frozen_at_accept_time(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.objects.create(app_key="notify-frozen-channel", name="Frozen")
    original = app.notification_channels.get(is_active=True)
    _seed_user(authentik="frozen-user", dingtalk="frozen-dt")
    message = _accept(app, ["frozen-user"])
    original.is_active = False
    original.save(update_fields=["is_active", "updated_at"])
    _ = AppNotificationChannel.objects.create(
        app=app,
        name="轮换后通道",
        dingtalk_app_key="new-key",
        dingtalk_app_secret="new-secret",  # noqa: S106 - 测试专用固定值。
        agent_id="2002",
        version=2,
    )
    used_channels: list[int] = []
    client = MagicMock()
    client.send_work_notification.return_value = "frozen-task"

    def client_for_channel(channel: AppNotificationChannel) -> tuple[MagicMock, int]:
        used_channels.append(channel.id)
        return client, int(channel.agent_id)

    monkeypatch.setattr(
        "easyauth.notify.services._dingtalk_client_and_agent",
        client_for_channel,
    )
    deliver_message(str(message.id), 1)

    message.refresh_from_db()
    assert message.channel_id == original.id
    assert used_channels == [original.id]


def test_deliver_partial_batch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.objects.create(app_key="notify-sm-partial", name="Partial")
    _seed_user(authentik="p1", dingtalk="dt-p1")
    _seed_user(authentik="p2", dingtalk="dt-p2")
    message = _accept(app, ["p1", "p2"])

    def send_side_effect(**kwargs: object) -> str:
        userids = kwargs["userid_list"]
        assert isinstance(userids, list)
        # 同批一起失败/成功: 用第二次 generation 不好模拟两批, 这里用单批终端错误。
        message = "permission denied"
        raise DingTalkApiRequestError(message, errcode=88)

    _patch_dingtalk(monkeypatch, send_side_effect=send_side_effect)
    deliver_message(str(message.id), 1)

    message.refresh_from_db()
    assert message.status == NOTIFY_MESSAGE_STATUS_FAILED
    assert message.recipient_failed == 2  # noqa: PLR2004
    assert NotifyRecipient.objects.filter(
        message=message,
        error_code=NOTIFY_ERROR_DINGTALK_REJECTED,
    ).count() == 2  # noqa: PLR2004


def test_deliver_throttle_marks_throttled_and_reschedules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key="notify-sm-throttle", name="Throttle")
    _seed_user(authentik="t1", dingtalk="dt-t1")
    message = _accept(app, ["t1"])
    _patch_dingtalk(
        monkeypatch,
        send_side_effect=DingTalkApiRequestError("qps", errcode=90018),
    )

    before = timezone.now()
    deliver_message(str(message.id), 1)

    message.refresh_from_db()
    assert message.status == NOTIFY_MESSAGE_STATUS_SENDING
    recipient = NotifyRecipient.objects.get(message=message)
    assert recipient.status == NOTIFY_RECIPIENT_STATUS_THROTTLED
    event = OutboxEvent.objects.get(event_key=f"notify-delivery:{message.id}:2")
    delta = (event.available_at - before).total_seconds()
    assert NOTIFY_THROTTLE_RETRY_SECONDS - 5 <= delta <= NOTIFY_THROTTLE_RETRY_SECONDS + 10


def test_deliver_network_interrupt_keeps_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key="notify-sm-net", name="Net")
    _seed_user(authentik="n1", dingtalk="dt-n1")
    message = _accept(app, ["n1"])
    _patch_dingtalk(
        monkeypatch,
        send_side_effect=DingTalkApiUnavailableError("down"),
    )

    before = timezone.now()
    deliver_message(str(message.id), 1)

    message.refresh_from_db()
    assert message.status == NOTIFY_MESSAGE_STATUS_SENDING
    recipient = NotifyRecipient.objects.get(message=message)
    assert recipient.status == NOTIFY_RECIPIENT_STATUS_PENDING
    event = OutboxEvent.objects.get(event_key=f"notify-delivery:{message.id}:2")
    # 首轮 attempts=1 → 退避 delays[0]=60s
    assert event.available_at is not None
    delta = (event.available_at - before).total_seconds()
    assert 55 <= delta <= 70  # noqa: PLR2004


def test_deliver_http_5xx_keeps_pending_and_reschedules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """钉钉 HTTP 5xx 不得终态, 走常规退避(第 3 篇 §4)。"""
    app = App.objects.create(app_key="notify-sm-5xx", name="5xx")
    _seed_user(authentik="x1", dingtalk="dt-x1")
    message = _accept(app, ["x1"])
    _patch_dingtalk(
        monkeypatch,
        send_side_effect=DingTalkApiRequestError("gateway", status_code=502),
    )

    before = timezone.now()
    deliver_message(str(message.id), 1)

    message.refresh_from_db()
    assert message.status == NOTIFY_MESSAGE_STATUS_SENDING
    recipient = NotifyRecipient.objects.get(message=message)
    assert recipient.status == NOTIFY_RECIPIENT_STATUS_PENDING
    assert recipient.error_code == ""
    event = OutboxEvent.objects.get(event_key=f"notify-delivery:{message.id}:2")
    delta = (event.available_at - before).total_seconds()
    assert 55 <= delta <= 70  # noqa: PLR2004


def test_deliver_http_4xx_is_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.objects.create(app_key="notify-sm-4xx", name="4xx")
    _seed_user(authentik="f1", dingtalk="dt-f1")
    message = _accept(app, ["f1"])
    _patch_dingtalk(
        monkeypatch,
        send_side_effect=DingTalkApiRequestError("forbidden", status_code=403),
    )

    deliver_message(str(message.id), 1)

    message.refresh_from_db()
    assert message.status == NOTIFY_MESSAGE_STATUS_FAILED
    recipient = NotifyRecipient.objects.get(message=message)
    assert recipient.status == NOTIFY_RECIPIENT_STATUS_FAILED
    assert recipient.error_code == NOTIFY_ERROR_DINGTALK_REJECTED


def test_deliver_exhaust_marks_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.objects.create(app_key="notify-sm-exhaust", name="Exhaust")
    _seed_user(authentik="e1", dingtalk="dt-e1")
    message = _accept(app, ["e1"])
    _patch_dingtalk(
        monkeypatch,
        send_side_effect=DingTalkApiUnavailableError("down"),
    )

    for generation in range(1, MAX_DELIVERY_ATTEMPTS + 1):
        deliver_message(str(message.id), generation)
        message.refresh_from_db()

    message.refresh_from_db()
    assert message.status == NOTIFY_MESSAGE_STATUS_FAILED
    recipient = NotifyRecipient.objects.get(message=message)
    assert recipient.status == NOTIFY_RECIPIENT_STATUS_FAILED
    assert recipient.error_code == NOTIFY_ERROR_EXHAUSTED


def test_mixed_accept_fail_and_deliver_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key="notify-sm-mixed", name="Mixed")
    _seed_user(authentik="m1", dingtalk="dt-m1")
    message = _accept(app, ["m1", "dt:nobody"])
    assert message.status == NOTIFY_MESSAGE_STATUS_PENDING
    assert message.recipient_total == 2  # noqa: PLR2004
    _patch_dingtalk(monkeypatch, task_ids=["t-mixed"])

    deliver_message(str(message.id), 1)

    message.refresh_from_db()
    assert message.status == NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED
    assert message.recipient_sent == 1
    assert message.recipient_failed == 1
