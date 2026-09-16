from __future__ import annotations

from easyauth.applications.integration_settings import (
    INTEGRATION_SETTINGS_SINGLETON_ID,
    IntegrationSettings,
    dingtalk_runtime_config,
)
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
    """工作通知客户端: token 与 agent_id 取运行时 notify 三元组, 不用通道自带钉钉凭证。

    通道仍冻结在消息上(目录作用域); 发送身份走公司服务号, 未配齐则回退主应用。
    """
    _ = channel
    config = dingtalk_runtime_config()
    notify = config.notify
    if not notify.is_configured():
        raise DingTalkNotConfiguredError
    agent_id = notify.agent_id.strip()
    if not agent_id:
        raise ValueError(DINGTALK_AGENT_MISSING_MESSAGE)
    # agent_id 优先 int, 否则原样字符串。
    try:
        agent: str | int = int(agent_id)
    except ValueError:
        agent = agent_id
    return (
        DingTalkApiClient(
            app_key=notify.app_key,
            app_secret=notify.app_secret,
            timeout_seconds=config.timeout_seconds,
        ),
        agent,
    )


def notify_robot_enabled() -> bool:
    """服务号机器人 sidecar 全局开关; 无设置行时与列默认值一致(开启)。"""
    row = IntegrationSettings.objects.filter(pk=INTEGRATION_SETTINGS_SINGLETON_ID).first()
    if row is None:
        return True
    return row.dingtalk_notify_robot_enabled
