from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction
from django.utils import timezone

from easyauth.applications.models import App
from easyauth.notify.channel_config import active_notification_channel
from easyauth.notify.contracts import (
    IDEMPOTENCY_PAYLOAD_CONFLICT_MESSAGE,
    MSG_TOO_LARGE_MESSAGE,
    NOTIFY_CHANNEL_MISSING_MESSAGE,
    NOTIFY_DELIVERY_TASK_NAME,
    NOTIFY_MESSAGE_STATUS_FAILED,
    NOTIFY_MESSAGE_STATUS_PENDING,
    NOTIFY_MSG_MAX_BYTES,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    AcceptNotifyResult,
    NotifyAcceptError,
    ResolvedRecipient,
)
from easyauth.notify.messages import (
    NormalizedInput,
    NotifyMessageInput,
    build_dingtalk_msg,
    compute_payload_hash,
    dingtalk_msg_utf8_size,
    normalize_and_validate,
)
from easyauth.notify.models import NotifyMessage, NotifyRecipient
from easyauth.notify.recipients import (
    accept_time_rejected_count,
    assert_daily_quota,
    enforce_channel_scope,
    resolve_recipients,
)
from easyauth.outbox.services import enqueue_task

__all__ = [
    "NotifyAcceptanceInput",
    "NotifyCredentialInput",
    "NotifyMessageInput",
    "accept_notify_message",
]

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.applications.models import AppNotificationChannel


@dataclass(frozen=True, slots=True)
class NotifyCredentialInput:
    """受理时绑定的应用凭据身份。"""

    credential_type: str
    credential_id: int


@dataclass(frozen=True, slots=True)
class NotifyAcceptanceInput:
    """通知受理入口: 应用 + 消息正文 + 请求凭据。"""

    app: App
    message: NotifyMessageInput
    credential: NotifyCredentialInput


def accept_notify_message(acceptance: NotifyAcceptanceInput) -> AcceptNotifyResult:
    """受理一则通知: 校验/组装/解析/幂等/配额/落库/入队。返回 (result)。"""
    prepared = _prepare_acceptance(acceptance)
    existing = _existing_result(acceptance.app, prepared)
    if existing is not None:
        return existing

    channel, scoped = _scope_acceptance(acceptance.app, prepared)
    try:
        message = _persist_acceptance(acceptance.app, channel, scoped)
    except IntegrityError:
        if not scoped.normalized.dedup_key:
            raise
        return _concurrent_winner_result(acceptance.app, scoped)

    rejected = _rejected_count(scoped.resolved)
    return AcceptNotifyResult(
        message=message,
        accepted=True,
        recipient_total=len(scoped.resolved),
        recipient_rejected=rejected,
    )


@dataclass(frozen=True, slots=True)
class _AcceptanceData:
    normalized: NormalizedInput
    payload_hash: str
    resolved: list[ResolvedRecipient]
    requested_credential_type: str
    requested_credential_id: int


def _prepare_acceptance(acceptance: NotifyAcceptanceInput) -> _AcceptanceData:
    message = acceptance.message
    normalized = normalize_and_validate(message)
    msg = build_dingtalk_msg(
        template=normalized.template,
        title=normalized.title,
        content=normalized.content,
        deeplink_url=normalized.deeplink_url,
        deeplink_title=normalized.deeplink_title,
    )
    if dingtalk_msg_utf8_size(msg) > NOTIFY_MSG_MAX_BYTES:
        raise NotifyAcceptError(
            kind="validation_error",
            message=MSG_TOO_LARGE_MESSAGE,
            field="content",
        )

    resolved = resolve_recipients(message.recipients)
    payload_hash = compute_payload_hash(
        replace(
            message,
            template=normalized.template,
            title=normalized.title,
            content=normalized.content,
            deeplink_url=normalized.deeplink_url,
            deeplink_title=normalized.deeplink_title,
            biz_tag=normalized.biz_tag,
        ),
    )

    return _AcceptanceData(
        normalized=normalized,
        payload_hash=payload_hash,
        resolved=resolved,
        requested_credential_type=acceptance.credential.credential_type,
        requested_credential_id=acceptance.credential.credential_id,
    )


def _existing_result(app: App, data: _AcceptanceData) -> AcceptNotifyResult | None:
    if not data.normalized.dedup_key:
        return None
    existing = NotifyMessage.objects.filter(
        app=app,
        dedup_key=data.normalized.dedup_key,
    ).first()
    if existing is None:
        return None
    _assert_matching_payload(existing, data.payload_hash)
    return _deduplicated_result(existing)


def _scope_acceptance(
    app: App,
    data: _AcceptanceData,
) -> tuple[AppNotificationChannel, _AcceptanceData]:
    channel = active_notification_channel(app.id)
    if channel is None:
        raise NotifyAcceptError(
            kind="dependency_unavailable",
            message=NOTIFY_CHANNEL_MISSING_MESSAGE,
        )
    scoped = _AcceptanceData(
        normalized=data.normalized,
        payload_hash=data.payload_hash,
        resolved=enforce_channel_scope(channel, data.resolved),
        requested_credential_type=data.requested_credential_type,
        requested_credential_id=data.requested_credential_id,
    )
    return channel, scoped


def _persist_acceptance(
    app: App,
    channel: AppNotificationChannel,
    data: _AcceptanceData,
) -> NotifyMessage:
    with transaction.atomic():
        locked_app = App.objects.select_for_update().get(id=app.id)
        # 日配额: 事务内先查后写。
        assert_daily_quota(app_id=locked_app.id, additional=len(data.resolved))
        return _create_message_with_recipients(
            app=locked_app,
            channel=channel,
            data=data,
        )


def _concurrent_winner_result(app: App, data: _AcceptanceData) -> AcceptNotifyResult:
    # 并发双写靠唯一约束兜底, 命中后按幂等语义返回。
    winner = NotifyMessage.objects.get(app=app, dedup_key=data.normalized.dedup_key)
    _assert_matching_payload(winner, data.payload_hash, suppress_context=True)
    return _deduplicated_result(winner)


def _assert_matching_payload(
    message: NotifyMessage,
    payload_hash: str,
    *,
    suppress_context: bool = False,
) -> None:
    if message.payload_hash == payload_hash:
        return
    error = NotifyAcceptError(
        kind="conflict",
        message=IDEMPOTENCY_PAYLOAD_CONFLICT_MESSAGE,
    )
    if suppress_context:
        raise error from None
    raise error


def _deduplicated_result(message: NotifyMessage) -> AcceptNotifyResult:
    return AcceptNotifyResult(
        message=message,
        accepted=False,
        recipient_total=message.recipient_total,
        recipient_rejected=accept_time_rejected_count(message),
    )


def _rejected_count(resolved: list[ResolvedRecipient]) -> int:
    return sum(1 for item in resolved if item.status == NOTIFY_RECIPIENT_STATUS_FAILED)


def _create_message_with_recipients(
    *,
    app: App,
    channel: AppNotificationChannel,
    data: _AcceptanceData,
) -> NotifyMessage:
    status, completed_at, rejected, pending_count = _initial_message_state(data.resolved)

    message = NotifyMessage.objects.create(
        app=app,
        channel=channel,
        template=data.normalized.template,
        title=data.normalized.title,
        content=data.normalized.content,
        deeplink_url=data.normalized.deeplink_url,
        deeplink_title=data.normalized.deeplink_title,
        dedup_key=data.normalized.dedup_key,
        payload_hash=data.payload_hash,
        biz_tag=data.normalized.biz_tag,
        status=status,
        recipient_total=len(data.resolved),
        recipient_sent=0,
        recipient_failed=rejected,
        requested_credential_type=data.requested_credential_type,
        requested_credential_id=data.requested_credential_id,
        completed_at=completed_at,
    )
    _ = NotifyRecipient.objects.bulk_create(
        [_recipient_row(message, item) for item in data.resolved],
    )
    if pending_count > 0:
        _ = enqueue_task(
            event_key=f"notify-delivery:{message.id}:1",
            task_name=NOTIFY_DELIVERY_TASK_NAME,
            args=[str(message.id), 1],
        )
    return message


def _initial_message_state(
    resolved: list[ResolvedRecipient],
) -> tuple[str, datetime | None, int, int]:
    rejected = _rejected_count(resolved)
    pending_count = len(resolved) - rejected
    if pending_count == 0:
        return NOTIFY_MESSAGE_STATUS_FAILED, timezone.now(), rejected, pending_count
    return NOTIFY_MESSAGE_STATUS_PENDING, None, rejected, pending_count


def _recipient_row(
    message: NotifyMessage,
    recipient: ResolvedRecipient,
) -> NotifyRecipient:
    return NotifyRecipient(
        message=message,
        raw_ref=recipient.raw_ref,
        user=recipient.user,
        dingtalk_corp_id=recipient.dingtalk_corp_id,
        dingtalk_source_slug=recipient.dingtalk_source_slug,
        dingtalk_userid=recipient.dingtalk_userid,
        status=recipient.status,
        error_code=recipient.error_code,
        error=recipient.error,
    )
