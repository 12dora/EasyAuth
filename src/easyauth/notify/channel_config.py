from __future__ import annotations

from django.conf import settings

from easyauth.applications.models import AppNotificationChannel
from easyauth.integrations.dingtalk.api_client import (
    DingTalkApiClient,
    DingTalkNotConfiguredError,
)
from easyauth.notify.contracts import DINGTALK_AGENT_MISSING_MESSAGE


def active_notification_channel(app_id: int) -> AppNotificationChannel | None:
    return (
        AppNotificationChannel.objects.filter(app_id=app_id, is_active=True)
        .exclude(dingtalk_app_key="")
        .exclude(dingtalk_app_secret="")
        .exclude(agent_id="")
        .exclude(directory_source_slug="")
        .exclude(corp_id="")
        .first()
    )


def dingtalk_client_and_agent(
    channel: AppNotificationChannel,
) -> tuple[DingTalkApiClient, str | int]:
    if not channel.dingtalk_app_key.strip() or not channel.dingtalk_app_secret:
        raise DingTalkNotConfiguredError
    agent_id = channel.agent_id.strip()
    if not agent_id:
        raise ValueError(DINGTALK_AGENT_MISSING_MESSAGE)
    # agent_id 优先 int, 否则原样字符串。
    try:
        agent: str | int = int(agent_id)
    except ValueError:
        agent = agent_id
    timeout_seconds = float(getattr(settings, "EASYAUTH_DINGTALK_HTTP_TIMEOUT_SECONDS", 5))
    return (
        DingTalkApiClient(
            app_key=channel.dingtalk_app_key,
            app_secret=channel.dingtalk_app_secret,
            timeout_seconds=timeout_seconds,
        ),
        agent,
    )
