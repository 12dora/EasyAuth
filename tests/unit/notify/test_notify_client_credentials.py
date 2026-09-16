from __future__ import annotations

import pytest

from easyauth.applications.integration_settings import IntegrationSettings
from easyauth.applications.models import App, AppNotificationChannel
from easyauth.integrations.dingtalk.api_client import DingTalkApiClient
from easyauth.notify.channel_config import dingtalk_client_and_agent

pytestmark = pytest.mark.django_db


def test_notify_client_uses_notify_agent_id_and_token_not_channel() -> None:
    row = IntegrationSettings.load()
    row.dingtalk_app_key = "main-key"
    row.dingtalk_app_secret = "main-secret"
    row.dingtalk_agent_id = "1001"
    row.dingtalk_notify_app_key = "svc-key"
    row.dingtalk_notify_app_secret = "svc-secret"
    row.dingtalk_notify_agent_id = "9001"
    row.save()
    app = App.objects.create(app_key="notify-client-app", name="Notify Client")
    channel = AppNotificationChannel.objects.create(
        app=app,
        name="通道",
        dingtalk_app_key="channel-key",
        dingtalk_app_secret="channel-secret",
        agent_id="2002",
        directory_source_slug="dingtalk-primary",
        corp_id="corp-delivery",
        version=1,
        is_active=True,
        created_by="pytest",
    )

    client, agent_id = dingtalk_client_and_agent(channel)
    main_client = DingTalkApiClient.from_settings()
    notify_client = DingTalkApiClient.from_notify_settings()

    assert agent_id == 9001
    assert client._app_key == "svc-key"  # noqa: SLF001 - 断言工作通知换票用服务号。
    assert client._app_secret == "svc-secret"  # noqa: SLF001
    assert notify_client._app_key == "svc-key"  # noqa: SLF001
    assert notify_client._app_secret == "svc-secret"  # noqa: SLF001
    assert main_client._app_key == "main-key"  # noqa: SLF001 - 目录同步/登录仍走主应用。
    assert main_client._app_secret == "main-secret"  # noqa: SLF001
