from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from easyauth.accounts.models import DingTalkUserMirror, UserMirror
from easyauth.applications.models import App, AppNotificationChannel
from easyauth.notify.acceptance import (
    NotifyAcceptanceInput,
    NotifyCredentialInput,
    NotifyMessageInput,
    accept_notify_message,
)
from easyauth.notify.contracts import NOTIFY_LEASE_SECONDS
from easyauth.notify.delivery import deliver_message
from easyauth.notify.models import (
    CREDENTIAL_TYPE_STATIC_TOKEN,
    NOTIFY_MESSAGE_STATUS_PENDING,
    NOTIFY_MESSAGE_STATUS_SENDING,
    NOTIFY_TEMPLATE_TEXT,
    NotifyMessage,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("notification_channel_for_apps")]

CORP_ID = "corp-claim"
SOURCE = "dingtalk-claim"


def _seed(authentik: str = "c1", dingtalk: str = "dt-c1") -> None:
    _ = DingTalkUserMirror.objects.create(
        source_slug=SOURCE,
        corp_id=CORP_ID,
        user_id=dingtalk,
        name=dingtalk,
        status="active",
    )
    _ = UserMirror.objects.create(
        authentik_user_id=authentik,
        dingtalk_source_slug=SOURCE,
        dingtalk_userid=dingtalk,
        dingtalk_corp_id=CORP_ID,
    )


def _accept(app: App) -> NotifyMessage:
    result = accept_notify_message(
        NotifyAcceptanceInput(
            app=app,
            message=NotifyMessageInput(
                template=NOTIFY_TEMPLATE_TEXT,
                content="claim-body",
                recipients=("c1",),
            ),
            credential=NotifyCredentialInput(
                credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
                credential_id=1,
            ),
        ),
    )
    return result.message


def test_concurrent_claim_only_one_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.objects.create(app_key="notify-claim-mutex", name="Claim")
    _seed()
    message = _accept(app)

    # 第一个执行体抢到租约后不释放(模拟进行中); 第二个应抢不到。
    held_token = "held-token-aaaaaaaaaaaaaaaaaa"
    _ = NotifyMessage.objects.filter(id=message.id).update(
        status=NOTIFY_MESSAGE_STATUS_SENDING,
        claim_token=held_token,
        lease_expires_at=timezone.now() + timedelta(seconds=NOTIFY_LEASE_SECONDS),
        attempts=1,
    )

    client = MagicMock()

    def client_for_channel(_channel: AppNotificationChannel) -> tuple[MagicMock, int]:
        return client, 1

    monkeypatch.setattr(
        "easyauth.notify.channel_config.dingtalk_client_and_agent",
        client_for_channel,
    )

    deliver_message(str(message.id), 2)

    message.refresh_from_db()
    assert message.claim_token == held_token
    client.send_work_notification.assert_not_called()


def test_expired_lease_can_be_taken_over(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.objects.create(app_key="notify-claim-expire", name="Expire")
    _seed(authentik="c2", dingtalk="dt-c2")
    result = accept_notify_message(
        NotifyAcceptanceInput(
            app=app,
            message=NotifyMessageInput(
                template=NOTIFY_TEMPLATE_TEXT,
                content="expire-body",
                recipients=("c2",),
            ),
            credential=NotifyCredentialInput(
                credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
                credential_id=1,
            ),
        ),
    )
    message = result.message
    _ = NotifyMessage.objects.filter(id=message.id).update(
        status=NOTIFY_MESSAGE_STATUS_SENDING,
        claim_token="old-token",
        lease_expires_at=timezone.now() - timedelta(seconds=1),
        attempts=1,
    )

    client = MagicMock()
    client.send_work_notification.return_value = "task-takeover"

    def client_for_channel(_channel: AppNotificationChannel) -> tuple[MagicMock, int]:
        return client, 1

    monkeypatch.setattr(
        "easyauth.notify.channel_config.dingtalk_client_and_agent",
        client_for_channel,
    )

    deliver_message(str(message.id), 2)

    message.refresh_from_db()
    assert message.claim_token == ""
    assert message.status != NOTIFY_MESSAGE_STATUS_PENDING
    client.send_work_notification.assert_called_once()
