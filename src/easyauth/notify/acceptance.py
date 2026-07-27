from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction
from django.utils import timezone

from easyauth.applications.models import App
from easyauth.notify.channel_config import active_notification_channel
from easyauth.notify.contracts import (
    DEFAULT_DEEPLINK_TITLE,
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

if TYPE_CHECKING:
    from collections.abc import Sequence

    from easyauth.applications.models import AppNotificationChannel


def accept_notify_message(  # noqa: PLR0913 - 受理入口完整业务事实。
    *,
    app: App,
    recipients: Sequence[str],
    template: str,
    title: str = "",
    content: str,
    deeplink_url: str = "",
    deeplink_title: str = DEFAULT_DEEPLINK_TITLE,
    dedup_key: str = "",
    biz_tag: str = "",
    requested_credential_type: str,
    requested_credential_id: int,
) -> AcceptNotifyResult:
    """受理一则通知: 校验/组装/解析/幂等/配额/落库/入队。返回 (result)。"""
    normalized = normalize_and_validate(
        template=template,
        title=title,
        content=content,
        deeplink_url=deeplink_url,
        deeplink_title=deeplink_title,
        dedup_key=dedup_key,
        biz_tag=biz_tag,
    )
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

    resolved = resolve_recipients(recipients)
    payload_hash = compute_payload_hash(
        template=normalized.template,
        title=normalized.title,
        content=normalized.content,
        deeplink_url=normalized.deeplink_url,
        deeplink_title=normalized.deeplink_title,
        biz_tag=normalized.biz_tag,
        recipients=list(recipients),
    )

    if normalized.dedup_key:
        existing = NotifyMessage.objects.filter(
            app=app,
            dedup_key=normalized.dedup_key,
        ).first()
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise NotifyAcceptError(
                    kind="conflict",
                    message=IDEMPOTENCY_PAYLOAD_CONFLICT_MESSAGE,
                )
            return AcceptNotifyResult(
                message=existing,
                accepted=False,
                recipient_total=existing.recipient_total,
                recipient_rejected=accept_time_rejected_count(existing),
            )

    channel = active_notification_channel(app.id)
    if channel is None:
        raise NotifyAcceptError(
            kind="dependency_unavailable",
            message=NOTIFY_CHANNEL_MISSING_MESSAGE,
        )
    resolved = enforce_channel_scope(channel, resolved)

    try:
        with transaction.atomic():
            locked_app = App.objects.select_for_update().get(id=app.id)
            # 日配额: 事务内先查后写。
            assert_daily_quota(app_id=locked_app.id, additional=len(resolved))
            message = _create_message_with_recipients(
                app=locked_app,
                channel=channel,
                normalized=normalized,
                payload_hash=payload_hash,
                resolved=resolved,
                requested_credential_type=requested_credential_type,
                requested_credential_id=requested_credential_id,
            )
    except IntegrityError:
        # 并发双写靠唯一约束兜底, 命中后按幂等语义返回。
        if not normalized.dedup_key:
            raise
        winner = NotifyMessage.objects.get(app=app, dedup_key=normalized.dedup_key)
        if winner.payload_hash != payload_hash:
            raise NotifyAcceptError(
                kind="conflict",
                message=IDEMPOTENCY_PAYLOAD_CONFLICT_MESSAGE,
            ) from None
        return AcceptNotifyResult(
            message=winner,
            accepted=False,
            recipient_total=winner.recipient_total,
            recipient_rejected=accept_time_rejected_count(winner),
        )

    rejected = sum(1 for item in resolved if item.status == NOTIFY_RECIPIENT_STATUS_FAILED)
    return AcceptNotifyResult(
        message=message,
        accepted=True,
        recipient_total=len(resolved),
        recipient_rejected=rejected,
    )


def _create_message_with_recipients(  # noqa: PLR0913 - 落库字段全集。
    *,
    app: App,
    channel: AppNotificationChannel,
    normalized: NormalizedInput,
    payload_hash: str,
    resolved: list[ResolvedRecipient],
    requested_credential_type: str,
    requested_credential_id: int,
) -> NotifyMessage:
    rejected = sum(1 for item in resolved if item.status == NOTIFY_RECIPIENT_STATUS_FAILED)
    pending_count = len(resolved) - rejected
    if pending_count == 0:
        status = NOTIFY_MESSAGE_STATUS_FAILED
        completed_at = timezone.now()
    else:
        status = NOTIFY_MESSAGE_STATUS_PENDING
        completed_at = None

    message = NotifyMessage.objects.create(
        app=app,
        channel=channel,
        template=normalized.template,
        title=normalized.title,
        content=normalized.content,
        deeplink_url=normalized.deeplink_url,
        deeplink_title=normalized.deeplink_title,
        dedup_key=normalized.dedup_key,
        payload_hash=payload_hash,
        biz_tag=normalized.biz_tag,
        status=status,
        recipient_total=len(resolved),
        recipient_sent=0,
        recipient_failed=rejected,
        requested_credential_type=requested_credential_type,
        requested_credential_id=requested_credential_id,
        completed_at=completed_at,
    )
    _ = NotifyRecipient.objects.bulk_create(
        [
            NotifyRecipient(
                message=message,
                raw_ref=item.raw_ref,
                user=item.user,
                dingtalk_corp_id=item.dingtalk_corp_id,
                dingtalk_source_slug=item.dingtalk_source_slug,
                dingtalk_userid=item.dingtalk_userid,
                status=item.status,
                error_code=item.error_code,
                error=item.error,
            )
            for item in resolved
        ],
    )
    if pending_count > 0:
        _ = enqueue_task(
            event_key=f"notify-delivery:{message.id}:1",
            task_name=NOTIFY_DELIVERY_TASK_NAME,
            args=[str(message.id), 1],
        )
    return message
