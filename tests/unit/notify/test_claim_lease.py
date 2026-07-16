from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from easyauth.accounts.models import DingTalkUserMirror, UserMirror
from easyauth.applications.models import App
from easyauth.notify.models import (
    CREDENTIAL_TYPE_STATIC_TOKEN,
    NOTIFY_MESSAGE_STATUS_PENDING,
    NOTIFY_MESSAGE_STATUS_SENDING,
    NOTIFY_TEMPLATE_TEXT,
    NotifyMessage,
)
from easyauth.notify.services import (
    NOTIFY_LEASE_SECONDS,
    accept_notify_message,
    deliver_message,
)

pytestmark = pytest.mark.django_db

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
        dingtalk_userid=dingtalk,
        dingtalk_corp_id=CORP_ID,
    )


def _accept(app: App) -> NotifyMessage:
    result = accept_notify_message(
        app=app,
        recipients=["c1"],
        template=NOTIFY_TEMPLATE_TEXT,
        content="claim-body",
        requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
        requested_credential_id=1,
    )
    return result.message


def test_concurrent_claim_only_one_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.objects.create(app_key="notify-claim-mutex", name="Claim")
    _seed()
    message = _accept(app)

    # 第一个执行体抢到租约后不释放(模拟进行中); 第二个应抢不到。
    held_token = "held-token-aaaaaaaaaaaaaaaaaa"  # noqa: S105 - 测试 claim token。
    _ = NotifyMessage.objects.filter(id=message.id).update(
        status=NOTIFY_MESSAGE_STATUS_SENDING,
        claim_token=held_token,
        lease_expires_at=timezone.now() + timedelta(seconds=NOTIFY_LEASE_SECONDS),
        attempts=1,
    )

    client = MagicMock()
    monkeypatch.setattr(
        "easyauth.notify.services._dingtalk_client_and_agent",
        lambda: (client, 1),
    )

    deliver_message(str(message.id), 2)

    message.refresh_from_db()
    assert message.claim_token == held_token
    client.send_work_notification.assert_not_called()


def test_expired_lease_can_be_taken_over(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.objects.create(app_key="notify-claim-expire", name="Expire")
    _seed(authentik="c2", dingtalk="dt-c2")
    result = accept_notify_message(
        app=app,
        recipients=["c2"],
        template=NOTIFY_TEMPLATE_TEXT,
        content="expire-body",
        requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
        requested_credential_id=1,
    )
    message = result.message
    _ = NotifyMessage.objects.filter(id=message.id).update(
        status=NOTIFY_MESSAGE_STATUS_SENDING,
        claim_token="old-token",  # noqa: S106
        lease_expires_at=timezone.now() - timedelta(seconds=1),
        attempts=1,
    )

    client = MagicMock()
    client.send_work_notification.return_value = "task-takeover"
    monkeypatch.setattr(
        "easyauth.notify.services._dingtalk_client_and_agent",
        lambda: (client, 1),
    )

    deliver_message(str(message.id), 2)

    message.refresh_from_db()
    assert message.claim_token == ""
    assert message.status != NOTIFY_MESSAGE_STATUS_PENDING
    client.send_work_notification.assert_called_once()
