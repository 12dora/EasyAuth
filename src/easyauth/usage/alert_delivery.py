from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Final

from django.utils import timezone

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import CAPABILITY_NOTIFY, App, AppCredential
from easyauth.notify.acceptance import (
    NotifyAcceptanceInput,
    NotifyCredentialInput,
    accept_notify_message,
)
from easyauth.notify.channel_config import active_notification_channel
from easyauth.notify.contracts import NotifyAcceptError
from easyauth.notify.messages import NotifyMessageInput
from easyauth.usage.config import UsageConfig, load

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.usage.models import UsageAlertEvent

SENDER_APP_MISSING: Final = "发送方应用未就绪"
SENDER_CREDENTIAL_MISSING: Final = "发送方凭据未就绪"
SENDER_CHANNEL_MISSING: Final = "发送方通知通道未就绪"
NO_RECIPIENTS: Final = "没有可投递的控制台管理员"
ALERT_TITLE: Final = "EasyAuth 用量告警"
ALERT_BIZ_TAG: Final = "usage.alert"


def sender_status() -> tuple[bool, str | None, int]:
    return inspect_sender(load())


def inspect_sender(config: UsageConfig) -> tuple[bool, str | None, int]:
    count = len(resolvable_admin_refs())
    problem = identity_problem(config.alerts.sender_app_key)
    if problem is not None:
        return False, problem, count
    if count == 0:
        return False, NO_RECIPIENTS, 0
    return True, None, count


def identity_problem(app_key: str) -> str | None:
    identity = App.objects.filter(app_key=app_key, is_active=True).first()
    if identity is None:
        return SENDER_APP_MISSING
    if notify_credential(identity) is None:
        return SENDER_CREDENTIAL_MISSING
    if active_notification_channel(identity.id) is None:
        return SENDER_CHANNEL_MISSING
    return None


def notify_credential(identity: App) -> AppCredential | None:
    return next(
        (
            item
            for item in AppCredential.objects.filter(app=identity, is_active=True).order_by("id")
            if CAPABILITY_NOTIFY in item.capabilities
        ),
        None,
    )


def resolvable_admin_refs() -> tuple[str, ...]:
    rows = UserMirror.objects.filter(
        is_console_admin=True,
        status=USER_STATUS_ACTIVE,
    ).exclude(dingtalk_userid="").order_by("authentik_user_id")
    return tuple(row.authentik_user_id for row in rows)


def send_merged_alert(
    events: tuple[UsageAlertEvent, ...],
    now: datetime,
    config: UsageConfig,
) -> str | None:
    ready, problem, _count = inspect_sender(config)
    if not ready:
        return problem
    identity = App.objects.filter(
        app_key=config.alerts.sender_app_key,
        is_active=True,
    ).first()
    credential = notify_credential(identity) if identity is not None else None
    if identity is None or credential is None:
        return SENDER_APP_MISSING
    refs = resolvable_admin_refs()
    if not refs:
        return NO_RECIPIENTS
    return _accept(identity, credential, events, now, refs)


def _accept(
    identity: App,
    credential: AppCredential,
    events: tuple[UsageAlertEvent, ...],
    now: datetime,
    refs: tuple[str, ...],
) -> str | None:
    message = NotifyMessageInput(
        title=ALERT_TITLE,
        content=_build_body(events, now),
        recipients=refs,
        dedup_key=_dedup_key(events, now),
        biz_tag=ALERT_BIZ_TAG,
    )
    try:
        _ = accept_notify_message(
            NotifyAcceptanceInput(
                app=identity,
                message=message,
                credential=NotifyCredentialInput(
                    credential_type=credential.credential_type,
                    credential_id=credential.id,
                ),
            ),
        )
    except NotifyAcceptError as error:
        return str(error)
    return None


def _build_body(events: tuple[UsageAlertEvent, ...], now: datetime) -> str:
    stamp = timezone.localtime(now).strftime("%Y-%m-%d %H:%M %z")
    lines = [f"时间: {stamp}", ""]
    lines.extend(f"- {event.detail}" for event in events)
    return "\n".join(lines)


def _dedup_key(events: tuple[UsageAlertEvent, ...], now: datetime) -> str:
    parts = sorted(
        f"{event.kind}:{event.metric}:{event.scope}:{event.period_key}:{event.threshold_percent}"
        for event in events
    )
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
    minute = timezone.localtime(now).strftime("%Y%m%d%H%M")
    return f"usage:{digest}:{minute}"
