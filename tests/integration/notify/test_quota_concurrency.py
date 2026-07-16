from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connection

from easyauth.accounts.models import DingTalkUserMirror, UserMirror
from easyauth.applications.models import (
    CAPABILITY_NOTIFY,
    App,
    AppCapability,
    AppNotificationChannel,
)
from easyauth.notify.models import CREDENTIAL_TYPE_STATIC_TOKEN, NOTIFY_TEMPLATE_TEXT
from easyauth.notify.services import NotifyAcceptError, accept_notify_message

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="并发配额锁需要 PostgreSQL 行锁语义。",
    ),
]


def test_daily_quota_is_atomic_across_concurrent_accepts() -> None:
    app = App.objects.create(app_key="notify-quota-concurrent", name="Quota Concurrent")
    _ = AppCapability.objects.create(
        app=app,
        capability=CAPABILITY_NOTIFY,
        enabled=True,
        config={"daily_recipient_quota": 1},
    )
    _ = AppNotificationChannel.objects.create(
        app=app,
        name="Quota Channel",
        dingtalk_app_key="quota-key",
        dingtalk_app_secret="quota-secret",  # noqa: S106
        agent_id="1001",
        directory_source_slug="dingtalk",
        corp_id="quota-corp",
        version=1,
    )
    for index in range(2):
        userid = f"quota-user-{index}"
        _ = DingTalkUserMirror.objects.create(
            source_slug="dingtalk",
            corp_id="quota-corp",
            user_id=userid,
            name=userid,
            status="active",
        )
        _ = UserMirror.objects.create(
            authentik_user_id=f"quota-auth-{index}",
            dingtalk_userid=userid,
            dingtalk_corp_id="quota-corp",
        )

    barrier = Barrier(2)

    def accept(index: int) -> str:
        close_old_connections()
        try:
            _ = barrier.wait(timeout=5)
            try:
                result = accept_notify_message(
                    app=App.objects.get(id=app.id),
                    recipients=[f"quota-auth-{index}"],
                    template=NOTIFY_TEMPLATE_TEXT,
                    content=f"quota-{index}",
                    requested_credential_type=CREDENTIAL_TYPE_STATIC_TOKEN,
                    requested_credential_id=1,
                )
            except NotifyAcceptError as error:
                return error.kind
            return "accepted" if result.accepted else "dedup"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(accept, range(2)))

    assert outcomes == ["accepted", "throttled"]
