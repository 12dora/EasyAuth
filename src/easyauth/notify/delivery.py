from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, cast

from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from easyauth.audit.services import AuditRecord, AuditService
from easyauth.integrations.dingtalk.api_client import (
    DingTalkApiClient,
    DingTalkApiRequestError,
    DingTalkApiUnavailableError,
    DingTalkNotConfiguredError,
    DingTalkRobotOtoResult,
    chunk_robot_user_ids,
)
from easyauth.notify import channel_config
from easyauth.notify.contracts import (
    DINGTALK_THROTTLE_ERRCODES,
    MAX_DELIVERY_ATTEMPTS,
    NOTIFY_BATCH_SIZE,
    NOTIFY_DELIVERY_TASK_NAME,
    NOTIFY_ERROR_DINGTALK_REJECTED,
    NOTIFY_ERROR_EXHAUSTED,
    NOTIFY_ERROR_MAX_CHARS,
    NOTIFY_LEASE_SECONDS,
    NOTIFY_MAX_CHUNKS_PER_RUN,
    NOTIFY_MESSAGE_STATUS_COMPLETED,
    NOTIFY_MESSAGE_STATUS_FAILED,
    NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED,
    NOTIFY_MESSAGE_STATUS_PENDING,
    NOTIFY_MESSAGE_STATUS_SENDING,
    NOTIFY_RECIPIENT_STATUS_DELIVERED,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_PENDING,
    NOTIFY_RECIPIENT_STATUS_SENT,
    NOTIFY_RECIPIENT_STATUS_THROTTLED,
    NOTIFY_RETRY_DELAYS_SECONDS,
    NOTIFY_THROTTLE_RETRY_SECONDS,
)
from easyauth.notify.messages import DingTalkMsgSource, build_dingtalk_msg
from easyauth.notify.models import (
    NOTIFY_ROBOT_STATUS_FAILED,
    NOTIFY_ROBOT_STATUS_SENT,
    NotifyMessage,
    NotifyRecipient,
)
from easyauth.notify.robot import build_robot_message_parts
from easyauth.outbox.services import enqueue_task

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

logger = logging.getLogger(__name__)


def deliver_message(message_id: str, generation: int) -> None:
    """单条消息一轮投递: 抢租约 → 分批调钉钉 → 推进状态 → 排程下一轮或收敛。"""
    claimed = _claim_message(message_id)
    if claimed is None:
        return
    message = claimed.message
    claim_token = claimed.claim_token

    open_recipients = _open_recipients(message)
    if not open_recipients:
        _refresh_and_maybe_finalize(message, claim_token=claim_token)
        return

    delivery = _delivery_context(message, claim_token)
    if delivery is None:
        _schedule_or_finalize(
            message,
            claim_token=claim_token,
            generation=generation,
            network_interrupted=True,
        )
        return

    network_interrupted = _send_recipient_chunks(delivery, open_recipients)
    _complete_delivery_round(
        message,
        claim_token=claim_token,
        generation=generation,
        network_interrupted=network_interrupted,
    )


@dataclass(frozen=True, slots=True)
class _DeliveryContext:
    message: NotifyMessage
    claim_token: str
    client: DingTalkApiClient
    agent_id: str | int
    msg: dict[str, object]
    robot_enabled: bool
    robot_title: str
    robot_text: str
    robot_single_url: str


def _open_recipients(message: NotifyMessage) -> list[NotifyRecipient]:
    return list(
        NotifyRecipient.objects.filter(
            message_id=message.id,
            status__in=(NOTIFY_RECIPIENT_STATUS_PENDING, NOTIFY_RECIPIENT_STATUS_THROTTLED),
        )
        .order_by("id")
        .all()[: NOTIFY_BATCH_SIZE * NOTIFY_MAX_CHUNKS_PER_RUN],
    )


def _delivery_context(message: NotifyMessage, claim_token: str) -> _DeliveryContext | None:
    try:
        client, agent_id = channel_config.dingtalk_client_and_agent(message.channel)
    except (DingTalkNotConfiguredError, ValueError) as error:
        # 配置缺失视为可恢复: 保持 pending, 走常规退避; 健康探测补齐后自动恢复。
        _record_network_error(message, claim_token, error)
        return None
    sent_at = timezone.now()
    source = DingTalkMsgSource(
        title=message.title,
        content=message.content,
        deeplink_url=message.deeplink_url,
        fields=_stored_form_fields(message),
        app_display_name=message.app_display_name,
        author=message.author,
    )
    msg = build_dingtalk_msg(app=message.app, source=source, sent_at=sent_at)
    robot_title, robot_text = build_robot_message_parts(
        app=message.app,
        source=source,
        sent_at=sent_at,
    )
    return _DeliveryContext(
        message=message,
        claim_token=claim_token,
        client=client,
        agent_id=agent_id,
        msg=msg,
        robot_enabled=channel_config.notify_robot_enabled(),
        robot_title=robot_title,
        robot_text=robot_text,
        robot_single_url=message.deeplink_url,
    )


def _stored_form_fields(message: NotifyMessage) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    for item in message.form_fields:
        if not isinstance(item, dict):
            message_text = "通知表单字段必须为对象列表。"
            raise TypeError(message_text)
        key = item.get("key")
        value = item.get("value")
        if not isinstance(key, str) or not isinstance(value, str):
            message_text = "通知表单字段必须含字符串 key/value。"
            raise TypeError(message_text)
        rows.append((key, value))
    return tuple(rows)


def _send_recipient_chunks(
    delivery: _DeliveryContext,
    open_recipients: list[NotifyRecipient],
) -> bool:
    chunks = [
        open_recipients[i : i + NOTIFY_BATCH_SIZE]
        for i in range(0, len(open_recipients), NOTIFY_BATCH_SIZE)
    ]
    return any(_send_recipient_chunk(delivery, chunk) for chunk in chunks)


def _send_recipient_chunk(
    delivery: _DeliveryContext,
    chunk: Sequence[NotifyRecipient],
) -> bool:
    userids = [row.dingtalk_userid for row in chunk if row.dingtalk_userid]
    if not userids:
        return False
    network_interrupted = _send_work_notice(delivery, chunk, userids)
    # 机器人 sidecar 与工作通知独立: 无论 OA 成败都尝试, 结果互不改写对方状态。
    _send_robot_channel(delivery, chunk)
    return network_interrupted


def _send_work_notice(
    delivery: _DeliveryContext,
    chunk: Sequence[NotifyRecipient],
    userids: list[str],
) -> bool:
    try:
        task_id = delivery.client.send_work_notification(
            agent_id=delivery.agent_id,
            userid_list=userids,
            msg=delivery.msg,
        )
    except DingTalkApiUnavailableError as error:
        _record_network_error(delivery.message, delivery.claim_token, error)
        return True
    except DingTalkApiRequestError as error:
        return _handle_request_error(delivery, chunk, error)
    _mark_chunk_sent(chunk, task_id=task_id)
    return False


def _send_robot_channel(
    delivery: _DeliveryContext,
    chunk: Sequence[NotifyRecipient],
) -> None:
    if not delivery.robot_enabled:
        return
    pending = [row for row in chunk if row.dingtalk_userid and row.robot_status is None]
    if not pending:
        return
    by_userid = {row.dingtalk_userid: row for row in pending}
    userids = [row.dingtalk_userid for row in pending]
    for batch_ids in chunk_robot_user_ids(userids):
        _send_robot_batch(delivery, by_userid, batch_ids)


def _send_robot_batch(
    delivery: _DeliveryContext,
    by_userid: dict[str, NotifyRecipient],
    batch_ids: tuple[str, ...],
) -> None:
    recipients = tuple(by_userid[userid] for userid in batch_ids)
    try:
        results = delivery.client.send_robot_oto_messages(
            robot_code=delivery.client.app_key,
            user_ids=batch_ids,
            title=delivery.robot_title,
            text=delivery.robot_text,
            single_url=delivery.robot_single_url,
        )
    except (DingTalkApiUnavailableError, DingTalkApiRequestError) as error:
        logger.warning(
            "notify_robot_send_failed message_id=%s userids=%s error=%s",
            delivery.message.id,
            ",".join(batch_ids),
            error,
        )
        _mark_robot_failed(recipients, error=str(error)[:NOTIFY_ERROR_MAX_CHARS])
        return
    for result in results:
        _apply_robot_result(by_userid, result)


def _apply_robot_result(
    by_userid: dict[str, NotifyRecipient],
    result: DingTalkRobotOtoResult,
) -> None:
    sent_ids: list[int] = []
    invalid_ids: list[int] = []
    flow_ids: list[int] = []
    for userid in result.user_ids:
        row = by_userid.get(userid)
        if row is None:
            continue
        if userid in result.invalid_staff_ids:
            invalid_ids.append(row.id)
        elif userid in result.flow_controlled_staff_ids:
            flow_ids.append(row.id)
        else:
            sent_ids.append(row.id)
    _mark_robot_sent(sent_ids, process_query_key=result.process_query_key)
    _mark_robot_failed_ids(invalid_ids, error="钉钉机器人返回无效员工。")
    _mark_robot_failed_ids(flow_ids, error="钉钉机器人流控。")


def _mark_robot_sent(ids: Sequence[int], *, process_query_key: str) -> None:
    if not ids:
        return
    now = timezone.now()
    _ = NotifyRecipient.objects.filter(id__in=ids, robot_status__isnull=True).update(
        robot_status=NOTIFY_ROBOT_STATUS_SENT,
        robot_process_query_key=process_query_key,
        robot_error=None,
        updated_at=now,
    )


def _mark_robot_failed(chunk: Sequence[NotifyRecipient], *, error: str) -> None:
    _mark_robot_failed_ids([row.id for row in chunk], error=error)


def _mark_robot_failed_ids(ids: Sequence[int], *, error: str) -> None:
    if not ids:
        return
    now = timezone.now()
    _ = NotifyRecipient.objects.filter(id__in=ids, robot_status__isnull=True).update(
        robot_status=NOTIFY_ROBOT_STATUS_FAILED,
        robot_error=error,
        updated_at=now,
    )


def _handle_request_error(
    delivery: _DeliveryContext,
    chunk: Sequence[NotifyRecipient],
    error: DingTalkApiRequestError,
) -> bool:
    if error.errcode is not None and error.errcode in DINGTALK_THROTTLE_ERRCODES:
        _mark_chunk_throttled(chunk, error=str(error)[:NOTIFY_ERROR_MAX_CHARS])
        return False
    if _is_retryable_request_error(error):
        # 钉钉 5xx / 无业务 errcode 的 HTTP 层故障: 保持原状态, 常规退避。
        _record_network_error(delivery.message, delivery.claim_token, error)
        return True
    _fail_open_recipients(
        chunk,
        error_code=NOTIFY_ERROR_DINGTALK_REJECTED,
        error=str(error)[:NOTIFY_ERROR_MAX_CHARS],
    )
    return False


def _record_network_error(
    message: NotifyMessage,
    claim_token: str,
    error: Exception,
) -> None:
    _ = NotifyMessage.objects.filter(id=message.id, claim_token=claim_token).update(
        last_error=str(error)[:NOTIFY_ERROR_MAX_CHARS],
    )


def _complete_delivery_round(
    message: NotifyMessage,
    *,
    claim_token: str,
    generation: int,
    network_interrupted: bool,
) -> None:
    message.refresh_from_db()
    refresh_message_counts(message)
    message.refresh_from_db()
    _schedule_or_finalize(
        message,
        claim_token=claim_token,
        generation=generation,
        network_interrupted=network_interrupted,
    )


@dataclass(frozen=True, slots=True)
class _ClaimedMessage:
    message: NotifyMessage
    claim_token: str


def _claim_message(message_id: str) -> _ClaimedMessage | None:
    now = timezone.now()
    claim_token = uuid.uuid4().hex
    try:
        message_uuid = uuid.UUID(str(message_id))
    except ValueError:
        return None
    updated = (
        NotifyMessage.objects.filter(
            id=message_uuid,
            status__in=(NOTIFY_MESSAGE_STATUS_PENDING, NOTIFY_MESSAGE_STATUS_SENDING),
        )
        .filter(
            Q(claim_token="") | Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now),
        )
        .update(
            status=NOTIFY_MESSAGE_STATUS_SENDING,
            attempts=F("attempts") + 1,
            claim_token=claim_token,
            lease_expires_at=now + timedelta(seconds=NOTIFY_LEASE_SECONDS),
            updated_at=now,
        )
    )
    if updated != 1:
        return None
    message = NotifyMessage.objects.filter(id=message_uuid).first()
    if message is None:
        return None
    return _ClaimedMessage(message=message, claim_token=claim_token)


def _is_retryable_request_error(error: DingTalkApiRequestError) -> bool:
    """常规失败可退避: 钉钉 5xx、或无 oapi 业务 errcode 的瞬时响应问题。

    业务 errcode(非频控)与明确 HTTP 4xx 为终态, 不重试。
    """
    if error.errcode is not None:
        return False
    if error.status_code is not None:
        return error.status_code >= 500  # noqa: PLR2004 - HTTP 5xx 阈值。
    # 无 status_code/errcode: 多为响应体解析/大小限制等瞬时故障, 走退避。
    return True


def _mark_chunk_sent(chunk: Sequence[NotifyRecipient], *, task_id: str) -> None:
    now = timezone.now()
    ids = [row.id for row in chunk]
    _ = NotifyRecipient.objects.filter(
        id__in=ids,
        status__in=(NOTIFY_RECIPIENT_STATUS_PENDING, NOTIFY_RECIPIENT_STATUS_THROTTLED),
    ).update(
        status=NOTIFY_RECIPIENT_STATUS_SENT,
        dingtalk_task_id=task_id,
        sent_at=now,
        error_code="",
        error="",
        updated_at=now,
    )


def _mark_chunk_throttled(chunk: Sequence[NotifyRecipient], *, error: str) -> None:
    now = timezone.now()
    ids = [row.id for row in chunk]
    _ = NotifyRecipient.objects.filter(
        id__in=ids,
        status__in=(NOTIFY_RECIPIENT_STATUS_PENDING, NOTIFY_RECIPIENT_STATUS_THROTTLED),
    ).update(
        status=NOTIFY_RECIPIENT_STATUS_THROTTLED,
        error=error,
        updated_at=now,
    )


def _fail_open_recipients(
    chunk: Sequence[NotifyRecipient],
    *,
    error_code: str,
    error: str,
) -> None:
    now = timezone.now()
    ids = [row.id for row in chunk]
    _ = NotifyRecipient.objects.filter(
        id__in=ids,
        status__in=(NOTIFY_RECIPIENT_STATUS_PENDING, NOTIFY_RECIPIENT_STATUS_THROTTLED),
    ).update(
        status=NOTIFY_RECIPIENT_STATUS_FAILED,
        error_code=error_code,
        error=error,
        updated_at=now,
    )


def refresh_message_counts(message: NotifyMessage) -> None:
    rows = cast(
        "list[dict[str, object]]",
        list(
            NotifyRecipient.objects.filter(message_id=message.id)
            .values("status")
            .annotate(count=Count("id")),
        ),
    )
    by_status: dict[str, int] = {}
    for row in rows:
        status_raw = row.get("status")
        count_raw = row.get("count")
        if (
            isinstance(status_raw, str)
            and isinstance(count_raw, int)
            and not isinstance(
                count_raw,
                bool,
            )
        ):
            by_status[status_raw] = count_raw
    sent = by_status.get(NOTIFY_RECIPIENT_STATUS_SENT, 0) + by_status.get(
        NOTIFY_RECIPIENT_STATUS_DELIVERED,
        0,
    )
    failed = by_status.get(NOTIFY_RECIPIENT_STATUS_FAILED, 0)
    _ = NotifyMessage.objects.filter(id=message.id).update(
        recipient_sent=sent,
        recipient_failed=failed,
        updated_at=timezone.now(),
    )


def open_recipient_counts(message_id: UUID) -> tuple[int, int]:
    pending = NotifyRecipient.objects.filter(
        message_id=message_id,
        status=NOTIFY_RECIPIENT_STATUS_PENDING,
    ).count()
    throttled = NotifyRecipient.objects.filter(
        message_id=message_id,
        status=NOTIFY_RECIPIENT_STATUS_THROTTLED,
    ).count()
    return pending, throttled


def _schedule_or_finalize(
    message: NotifyMessage,
    *,
    claim_token: str,
    generation: int,
    network_interrupted: bool,
) -> None:
    pending, throttled = open_recipient_counts(message.id)
    open_count = pending + throttled
    if open_count == 0:
        _finalize_message(message, claim_token=claim_token)
        return
    if message.attempts >= MAX_DELIVERY_ATTEMPTS:
        _exhaust_open_recipients(message.id)
        _finalize_message(message, claim_token=claim_token, exhausted=True)
        return

    if network_interrupted:
        countdown = _retry_delay_seconds(message.attempts)
    elif pending > 0:
        # 批上限未处理完: 立即继续; 否则常规退避已在 network 分支。
        countdown = 0
    else:
        countdown = NOTIFY_THROTTLE_RETRY_SECONDS

    next_generation = generation + 1
    with transaction.atomic():
        released = NotifyMessage.objects.filter(
            id=message.id,
            claim_token=claim_token,
            status=NOTIFY_MESSAGE_STATUS_SENDING,
        ).update(
            claim_token="",
            lease_expires_at=None,
            updated_at=timezone.now(),
        )
        if released != 1:
            return
        _ = enqueue_task(
            event_key=f"notify-delivery:{message.id}:{next_generation}",
            task_name=NOTIFY_DELIVERY_TASK_NAME,
            args=[str(message.id), next_generation],
            countdown=countdown,
        )


def _retry_delay_seconds(attempts: int) -> int:
    index = min(max(attempts - 1, 0), len(NOTIFY_RETRY_DELAYS_SECONDS) - 1)
    return NOTIFY_RETRY_DELAYS_SECONDS[index]


def _exhaust_open_recipients(message_id: UUID) -> None:
    now = timezone.now()
    _ = NotifyRecipient.objects.filter(
        message_id=message_id,
        status__in=(NOTIFY_RECIPIENT_STATUS_PENDING, NOTIFY_RECIPIENT_STATUS_THROTTLED),
    ).update(
        status=NOTIFY_RECIPIENT_STATUS_FAILED,
        error_code=NOTIFY_ERROR_EXHAUSTED,
        error="投递重试耗尽。",
        updated_at=now,
    )


def _refresh_and_maybe_finalize(message: NotifyMessage, *, claim_token: str) -> None:
    refresh_message_counts(message)
    message.refresh_from_db()
    pending, throttled = open_recipient_counts(message.id)
    if pending + throttled == 0:
        _finalize_message(message, claim_token=claim_token)
        return
    # 无 open 可处理但仍有 open(不应发生): 释放 claim 等待下次。
    _ = NotifyMessage.objects.filter(id=message.id, claim_token=claim_token).update(
        claim_token="",
        lease_expires_at=None,
        updated_at=timezone.now(),
    )


def _finalize_message(
    message: NotifyMessage,
    *,
    claim_token: str,
    exhausted: bool = False,
) -> None:
    refresh_message_counts(message)
    message.refresh_from_db()
    failed = message.recipient_failed
    total = message.recipient_total
    if failed <= 0:
        status = NOTIFY_MESSAGE_STATUS_COMPLETED
    elif failed >= total:
        status = NOTIFY_MESSAGE_STATUS_FAILED
    else:
        status = NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED
    now = timezone.now()
    updated = NotifyMessage.objects.filter(
        id=message.id,
        claim_token=claim_token,
    ).update(
        status=status,
        completed_at=now,
        claim_token="",
        lease_expires_at=None,
        updated_at=now,
    )
    if updated != 1:
        return
    message.refresh_from_db()
    _record_delivery_terminal(message, exhausted=exhausted)


def _record_delivery_terminal(message: NotifyMessage, *, exhausted: bool) -> None:
    action = "notify_delivery_exhausted" if exhausted else "notify_delivered"
    if exhausted:
        logger.error(
            "notify_delivery_exhausted message_id=%s app_id=%s attempts=%s failed=%s total=%s",
            message.id,
            message.app_id,
            message.attempts,
            message.recipient_failed,
            message.recipient_total,
        )
    _ = AuditService.record(
        AuditRecord(
            actor_type="system",
            actor_id="notify_delivery",
            action=action,
            target_type="notify_message",
            target_id=str(message.id),
            metadata={
                "status": message.status,
                "recipient_sent": message.recipient_sent,
                "recipient_failed": message.recipient_failed,
                "recipient_total": message.recipient_total,
                "attempts": message.attempts,
            },
        ),
    )
