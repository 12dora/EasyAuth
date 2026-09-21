from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, cast

from django.conf import settings
from django.db.models import F, Max, Min, Q
from django.utils import timezone

from easyauth.applications.models import AppNotificationChannel
from easyauth.integrations.dingtalk.api_client import (
    DingTalkApiClient,
    DingTalkApiRequestError,
    DingTalkApiUnavailableError,
    DingTalkForbiddenReceipt,
    DingTalkNotConfiguredError,
    DingTalkSendResult,
)
from easyauth.notify import channel_config
from easyauth.notify.contracts import (
    DINGTALK_PROGRESS_DONE,
    NOTIFY_ERROR_DINGTALK_DAILY_LIMIT,
    NOTIFY_ERROR_DINGTALK_DUPLICATE,
    NOTIFY_ERROR_DINGTALK_REJECTED,
    NOTIFY_ERROR_MAX_CHARS,
    NOTIFY_MESSAGE_STATUS_COMPLETED,
    NOTIFY_MESSAGE_STATUS_FAILED,
    NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED,
    NOTIFY_RECIPIENT_STATUS_DELIVERED,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_SENT,
    NOTIFY_RECONCILE_BACKOFF_SECONDS,
    NOTIFY_RECONCILE_CAP_REACHED_MESSAGE,
    NOTIFY_RECONCILE_MAX_ATTEMPTS,
    NOTIFY_RECONCILE_TASK_LIMIT,
    NOTIFY_RECONCILE_WINDOW_HOURS,
)
from easyauth.notify.delivery import open_recipient_counts, refresh_message_counts
from easyauth.notify.models import NotifyMessage, NotifyRecipient

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from django.db.models import QuerySet

logger = logging.getLogger(__name__)

_UNCONFIGURED_CHANNEL_MESSAGE: Final = "钉钉通知通道未配置。"


@dataclass(frozen=True, slots=True)
class _ReconcileWindow:
    now: datetime
    channel_tasks: tuple[tuple[int, str, int], ...]


def reconcile_send_results() -> int:
    """对 sent 收件人按 task_id 查钉钉回执, 升级 delivered/failed。返回处理的 task 数。"""
    window = _reconcile_run_window()
    if window is None:
        return 0
    processed, affected = _reconcile_selected_tasks(window)
    _refresh_affected_messages(affected)
    return processed


def _reconcile_run_window() -> _ReconcileWindow | None:
    if not getattr(settings, "EASYAUTH_NOTIFY_RECONCILE_ENABLED", True):
        return None
    now = timezone.now()
    window_start = now - timedelta(hours=NOTIFY_RECONCILE_WINDOW_HOURS)
    channel_tasks = select_reconcile_tasks(window_start, now)
    if not channel_tasks:
        return None
    return _ReconcileWindow(now=now, channel_tasks=tuple(channel_tasks))


def _reconcile_selected_tasks(window: _ReconcileWindow) -> tuple[int, set[UUID]]:
    processed = 0
    affected: set[UUID] = set()
    for channel_id, task_id, pre_claim_attempts in window.channel_tasks:
        message_ids = _reconcile_channel_task(
            channel_id=channel_id,
            task_id=task_id,
            now=window.now,
            pre_claim_attempts=pre_claim_attempts,
        )
        if not message_ids:
            continue
        affected.update(message_ids)
        processed += 1
    return processed, affected


def _reconcile_channel_task(
    *,
    channel_id: int,
    task_id: str,
    now: datetime,
    pre_claim_attempts: int,
) -> set[UUID] | None:
    try:
        result = _run_claimed_task(
            channel_id=channel_id,
            task_id=task_id,
            now=now,
            pre_claim_attempts=pre_claim_attempts,
        )
    except Exception:
        logger.exception(
            "钉钉回执对账未预期异常 channel_id=%s task_id=%s",
            channel_id,
            task_id,
        )
        return None
    return result


def _run_claimed_task(
    *,
    channel_id: int,
    task_id: str,
    now: datetime,
    pre_claim_attempts: int,
) -> set[UUID] | None:
    if not claim_reconcile_task(
        channel_id=channel_id,
        task_id=task_id,
        now=now,
        pre_claim_attempts=pre_claim_attempts,
    ):
        return None
    attempts_after = pre_claim_attempts + 1
    try:
        message_ids = _poll_claimed_task(
            channel_id=channel_id,
            task_id=task_id,
            now=now,
            attempts_after=attempts_after,
        )
    except (DingTalkApiRequestError, DingTalkApiUnavailableError) as error:
        _write_sent_outcome(
            channel_id=channel_id,
            task_id=task_id,
            checked_at=now,
            error=str(error),
            attempts_after=attempts_after,
        )
        return None
    return message_ids


def _poll_claimed_task(
    *,
    channel_id: int,
    task_id: str,
    now: datetime,
    attempts_after: int,
) -> set[UUID] | None:
    resolved = _resolve_task_client(channel_id=channel_id)
    if not isinstance(resolved, tuple):
        _write_sent_outcome(
            channel_id=channel_id,
            task_id=task_id,
            checked_at=now,
            error=resolved,
            attempts_after=attempts_after,
        )
        return None
    client, agent_id = resolved
    message_ids = _reconcile_one_task(
        client=client,
        agent_id=agent_id,
        channel_id=channel_id,
        task_id=task_id,
        now=now,
    )
    _write_sent_outcome(
        channel_id=channel_id,
        task_id=task_id,
        checked_at=now,
        error=None,
        attempts_after=attempts_after,
    )
    return message_ids


def _resolve_task_client(
    *,
    channel_id: int,
) -> tuple[DingTalkApiClient, str | int] | str | None:
    channel = AppNotificationChannel.objects.filter(id=channel_id).first()
    if channel is None:
        return None
    try:
        resolved = channel_config.dingtalk_client_and_agent(channel)
    except (DingTalkNotConfiguredError, ValueError) as error:
        return str(error) or _UNCONFIGURED_CHANNEL_MESSAGE
    return resolved


def _refresh_affected_messages(message_ids: set[UUID]) -> None:
    for mid in message_ids:
        msg = NotifyMessage.objects.filter(id=mid).first()
        if msg is None:
            continue
        refresh_message_counts(msg)
        _maybe_rewrite_aggregate_after_reconcile(msg)


def select_reconcile_tasks(window_start: datetime, now: datetime) -> list[tuple[int, str, int]]:
    raw_tasks = list(
        NotifyRecipient.objects.filter(
            status=NOTIFY_RECIPIENT_STATUS_SENT,
            sent_at__gt=window_start,
            message__channel_id__isnull=False,
        )
        .exclude(dingtalk_task_id="")
        .values("message__channel_id", "dingtalk_task_id")
        .annotate(
            last_checked_at=Max("last_reconciled_at"),
            max_attempts=Max("reconcile_attempts"),
            next_due_at=Min("next_reconcile_at"),
        )
        .filter(max_attempts__lt=NOTIFY_RECONCILE_MAX_ATTEMPTS)
        .filter(Q(next_due_at__isnull=True) | Q(next_due_at__lte=now))
        .order_by(
            F("last_checked_at").asc(nulls_first=True),
            "message__channel_id",
            "dingtalk_task_id",
        )[:NOTIFY_RECONCILE_TASK_LIMIT],
    )
    typed = cast("list[dict[str, object]]", raw_tasks)
    tasks: list[tuple[int, str, int]] = []
    for row in typed:
        selected = _selected_task_from_row(row)
        if selected is None:
            continue
        tasks.append(selected)
    return tasks


def _selected_task_from_row(row: dict[str, object]) -> tuple[int, str, int] | None:
    channel_id = row.get("message__channel_id")
    task_id = row.get("dingtalk_task_id")
    pre_claim_attempts = row.get("max_attempts")
    if (
        isinstance(channel_id, int)
        and isinstance(task_id, str)
        and isinstance(pre_claim_attempts, int)
    ):
        return (channel_id, task_id, pre_claim_attempts)
    return None


def claim_reconcile_task(
    *,
    channel_id: int,
    task_id: str,
    now: datetime,
    pre_claim_attempts: int,
) -> bool:
    """原子认领该 task 的 SENT 行。命中 0 行表示已被并发 worker 认领。"""
    next_at = now + timedelta(seconds=_clamped_backoff_seconds(pre_claim_attempts))
    matched = NotifyRecipient.objects.filter(
        Q(next_reconcile_at__isnull=True) | Q(next_reconcile_at__lte=now),
        message__channel_id=channel_id,
        dingtalk_task_id=task_id,
        status=NOTIFY_RECIPIENT_STATUS_SENT,
        reconcile_attempts__lt=NOTIFY_RECONCILE_MAX_ATTEMPTS,
    ).update(
        reconcile_attempts=F("reconcile_attempts") + 1,
        last_reconciled_at=now,
        next_reconcile_at=next_at,
        updated_at=now,
    )
    return bool(matched)


def _clamped_backoff_seconds(pre_claim_attempts: int) -> int:
    last_index = len(NOTIFY_RECONCILE_BACKOFF_SECONDS) - 1
    index = min(max(pre_claim_attempts, 0), last_index)
    return NOTIFY_RECONCILE_BACKOFF_SECONDS[index]


def _sent_recipient_qs(*, channel_id: int, task_id: str) -> QuerySet[NotifyRecipient]:
    return NotifyRecipient.objects.filter(
        message__channel_id=channel_id,
        dingtalk_task_id=task_id,
        status=NOTIFY_RECIPIENT_STATUS_SENT,
    )


def _write_sent_outcome(
    *,
    channel_id: int,
    task_id: str,
    checked_at: datetime,
    error: str | None,
    attempts_after: int,
) -> None:
    qs = _sent_recipient_qs(channel_id=channel_id, task_id=task_id)
    if attempts_after >= NOTIFY_RECONCILE_MAX_ATTEMPTS:
        error_text = NOTIFY_RECONCILE_CAP_REACHED_MESSAGE
    elif error is None:
        error_text = ""
    else:
        error_text = error[:NOTIFY_ERROR_MAX_CHARS]
    _ = qs.update(error=error_text, updated_at=checked_at)


def _reconcile_one_task(
    *,
    client: DingTalkApiClient,
    agent_id: str | int,
    channel_id: int,
    task_id: str,
    now: datetime,
) -> set[UUID]:
    send_result = _fetch_completed_send_result(
        client=client,
        agent_id=agent_id,
        task_id=task_id,
    )
    if send_result is None:
        return set()
    return _apply_send_result(
        channel_id=channel_id,
        task_id=task_id,
        send_result=send_result,
        now=now,
    )


def _fetch_completed_send_result(
    *,
    client: DingTalkApiClient,
    agent_id: str | int,
    task_id: str,
) -> DingTalkSendResult | None:
    progress = client.get_send_progress(agent_id=agent_id, task_id=task_id)
    if progress.status != DINGTALK_PROGRESS_DONE:
        return None
    return client.get_send_result(agent_id=agent_id, task_id=task_id)


def _apply_send_result(
    *,
    channel_id: int,
    task_id: str,
    send_result: DingTalkSendResult,
    now: datetime,
) -> set[UUID]:
    rejected_userids = send_result.invalid_user_ids | send_result.failed_user_ids
    forbidden_by_code = _forbidden_userid_codes(send_result.forbidden_receipts)
    delivered_userids = send_result.read_user_ids | send_result.unread_user_ids
    for userid in send_result.forbidden_user_ids:
        _ = forbidden_by_code.setdefault(userid, NOTIFY_ERROR_DINGTALK_REJECTED)

    qs = NotifyRecipient.objects.filter(
        dingtalk_task_id=task_id,
        status=NOTIFY_RECIPIENT_STATUS_SENT,
        message__channel_id=channel_id,
    )
    recipients = list(qs)
    affected: set[UUID] = set()
    for row in recipients:
        userid = row.dingtalk_userid
        if userid in rejected_userids:
            affected.add(row.message_id)
            row.status = NOTIFY_RECIPIENT_STATUS_FAILED
            row.error_code = NOTIFY_ERROR_DINGTALK_REJECTED
            row.error = "钉钉回执: 无效用户或发送失败。"
            row.updated_at = now
            row.save(
                update_fields=["status", "error_code", "error", "updated_at"],
            )
            continue
        if userid in forbidden_by_code:
            affected.add(row.message_id)
            code = forbidden_by_code[userid]
            row.status = NOTIFY_RECIPIENT_STATUS_FAILED
            row.error_code = code
            if code == NOTIFY_ERROR_DINGTALK_DUPLICATE:
                row.error = "钉钉回执: 相同内容同人一天已发送。"
            elif code == NOTIFY_ERROR_DINGTALK_DAILY_LIMIT:
                row.error = "钉钉回执: 单应用对单人日上限。"
            else:
                row.error = "钉钉回执: 被流控过滤。"
            row.updated_at = now
            row.save(
                update_fields=["status", "error_code", "error", "updated_at"],
            )
            continue
        if userid not in delivered_userids:
            continue
        affected.add(row.message_id)
        row.status = NOTIFY_RECIPIENT_STATUS_DELIVERED
        row.delivered_at = now
        row.error_code = ""
        row.error = ""
        row.updated_at = now
        row.save(
            update_fields=["status", "delivered_at", "error_code", "error", "updated_at"],
        )
    return affected


def _forbidden_userid_codes(receipts: tuple[DingTalkForbiddenReceipt, ...]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in receipts:
        code_int = item.code
        if code_int == 143106:  # noqa: PLR2004 - 钉钉官方流控码。
            mapping[item.userid] = NOTIFY_ERROR_DINGTALK_DUPLICATE
        elif code_int == 143105:  # noqa: PLR2004 - 钉钉官方流控码。
            mapping[item.userid] = NOTIFY_ERROR_DINGTALK_DAILY_LIMIT
        else:
            mapping[item.userid] = NOTIFY_ERROR_DINGTALK_REJECTED
    return mapping


def _maybe_rewrite_aggregate_after_reconcile(message: NotifyMessage) -> None:
    """对账可能把 sent 改为 failed, 需把 completed 降为 partially_failed/failed。"""
    message.refresh_from_db()
    pending, throttled = open_recipient_counts(message.id)
    if pending + throttled > 0:
        return
    failed = message.recipient_failed
    total = message.recipient_total
    if failed <= 0:
        new_status = NOTIFY_MESSAGE_STATUS_COMPLETED
    elif failed >= total:
        new_status = NOTIFY_MESSAGE_STATUS_FAILED
    else:
        new_status = NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED
    if message.status == new_status:
        return
    now = timezone.now()
    updates: dict[str, object] = {
        "status": new_status,
        "updated_at": now,
    }
    if message.completed_at is None and new_status in {
        NOTIFY_MESSAGE_STATUS_COMPLETED,
        NOTIFY_MESSAGE_STATUS_PARTIALLY_FAILED,
        NOTIFY_MESSAGE_STATUS_FAILED,
    }:
        updates["completed_at"] = now
    _ = NotifyMessage.objects.filter(id=message.id).update(**updates)
