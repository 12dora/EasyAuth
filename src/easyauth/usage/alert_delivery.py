from __future__ import annotations

import hashlib
from dataclasses import dataclass
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
    from easyauth.usage.models import UsageAlertEvent

SENDER_APP_MISSING: Final = "发送方应用未就绪"
SENDER_CREDENTIAL_MISSING: Final = "发送方凭据未就绪"
SENDER_CHANNEL_MISSING: Final = "发送方通知通道未就绪"
NO_RECIPIENTS: Final = "没有可投递的控制台管理员"
ALERT_TITLE: Final = "EasyAuth 用量告警"
ALERT_BIZ_TAG: Final = "usage.alert"


@dataclass(frozen=True, slots=True)
class MergedAlertDelivery:
    failure_reason: str | None
    handed_off: bool


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
    config: UsageConfig,
) -> MergedAlertDelivery:
    ready, problem, _count = inspect_sender(config)
    if not ready:
        return MergedAlertDelivery(failure_reason=problem, handed_off=False)
    identity = App.objects.filter(
        app_key=config.alerts.sender_app_key,
        is_active=True,
    ).first()
    credential = notify_credential(identity) if identity is not None else None
    if identity is None or credential is None:
        return MergedAlertDelivery(failure_reason=SENDER_APP_MISSING, handed_off=False)
    refs = resolvable_admin_refs()
    if not refs:
        return MergedAlertDelivery(failure_reason=NO_RECIPIENTS, handed_off=False)
    return _accept(identity, credential, events, refs)


def batch_key_for_parts(parts: tuple[str, ...]) -> str:
    digest = hashlib.sha256("|".join(sorted(parts)).encode("utf-8")).hexdigest()[:24]
    return f"usage:{digest}"


def batch_key_for_events(events: tuple[UsageAlertEvent, ...]) -> str:
    return batch_key_for_parts(tuple(_event_part(event) for event in events))


def _accept(
    identity: App,
    credential: AppCredential,
    events: tuple[UsageAlertEvent, ...],
    refs: tuple[str, ...],
) -> MergedAlertDelivery:
    message = NotifyMessageInput(
        title=ALERT_TITLE,
        content=_build_body(events),
        recipients=refs,
        dedup_key=batch_key_for_events(events),
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
        return MergedAlertDelivery(failure_reason=str(error), handed_off=True)
    return MergedAlertDelivery(failure_reason=None, handed_off=True)


def _build_body(events: tuple[UsageAlertEvent, ...]) -> str:
    earliest = min(event.created_at for event in events)
    stamp = timezone.localtime(earliest).strftime("%Y-%m-%d %H:%M %z")
    lines = [f"时间: {stamp}", ""]
    lines.extend(f"- {event.detail}" for event in events)
    return "\n".join(lines)


def _event_part(event: UsageAlertEvent) -> str:
    threshold = event.threshold_percent
    return f"{event.kind}:{event.metric}:{event.scope}:{event.period_key}:{threshold}"
