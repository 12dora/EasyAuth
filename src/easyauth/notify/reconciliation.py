from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, cast

from django.conf import settings
from django.db.models import F, Max
from django.utils import timezone

from easyauth.applications.models import AppNotificationChannel
from easyauth.integrations.dingtalk.api_client import (
    DingTalkApiClient,
    DingTalkApiRequestError,
    DingTalkApiUnavailableError,
    DingTalkForbiddenReceipt,
    DingTalkNotConfiguredError,
    DingTalkSendProgress,
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
    NOTIFY_RECONCILE_TASK_LIMIT,
    NOTIFY_RECONCILE_WINDOW_HOURS,
)
from easyauth.notify.delivery import open_recipient_counts, refresh_message_counts
from easyauth.notify.models import NotifyMessage, NotifyRecipient

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class _ReconcileWindow:
    now: datetime
    channel_tasks: tuple[tuple[int, str], ...]


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
    channel_tasks = select_reconcile_tasks(window_start)
    if not channel_tasks:
        return None
    return _ReconcileWindow(now=now, channel_tasks=tuple(channel_tasks))


def _reconcile_selected_tasks(window: _ReconcileWindow) -> tuple[int, set[UUID]]:
    processed = 0
    affected: set[UUID] = set()
    for channel_id, task_id in window.channel_tasks:
        message_ids = _reconcile_channel_task(
            channel_id=channel_id,
            task_id=task_id,
            now=window.now,
        )
        if not message_ids:
            continue
        affected.update(message_ids)
        processed += 1
    return processed, affected


def _resolve_task_client(
    *,
    channel_id: int,
    task_id: str,
    now: datetime,
) -> tuple[DingTalkApiClient, str | int] | None:
    channel = AppNotificationChannel.objects.filter(id=channel_id).first()
    if channel is None:
        _mark_task_reconciled(channel_id=channel_id, task_id=task_id, checked_at=now)
        return None
    try:
        return channel_config.dingtalk_client_and_agent(channel)
    except (DingTalkNotConfiguredError, ValueError) as error:
        _mark_task_reconcile_failed(
            channel_id=channel_id,
            task_id=task_id,
            checked_at=now,
            error=str(error) or "钉钉通知通道未配置。",
        )
        return None


def _reconcile_channel_task(
    *,
    channel_id: int,
    task_id: str,
    now: datetime,
) -> set[UUID] | None:
    resolved = _resolve_task_client(channel_id=channel_id, task_id=task_id, now=now)
    if resolved is None:
        return None
    client, agent_id = resolved
    try:
        message_ids = _reconcile_one_task(
            client=client,
            agent_id=agent_id,
            channel_id=channel_id,
            task_id=task_id,
            now=now,
        )
    except (DingTalkApiRequestError, DingTalkApiUnavailableError) as error:
        _mark_task_reconcile_failed(
            channel_id=channel_id,
            task_id=task_id,
            checked_at=now,
            error=str(error),
        )
        return None
    _mark_task_reconciled(channel_id=channel_id, task_id=task_id, checked_at=now)
    return message_ids


def _refresh_affected_messages(message_ids: set[UUID]) -> None:
    for mid in message_ids:
        msg = NotifyMessage.objects.filter(id=mid).first()
        if msg is None:
            continue
        refresh_message_counts(msg)
        _maybe_rewrite_aggregate_after_reconcile(msg)


def select_reconcile_tasks(window_start: datetime) -> list[tuple[int, str]]:
    raw_tasks = list(
        NotifyRecipient.objects.filter(
            status=NOTIFY_RECIPIENT_STATUS_SENT,
            sent_at__gt=window_start,
            message__channel_id__isnull=False,
        )
        .exclude(dingtalk_task_id="")
        .values("message__channel_id", "dingtalk_task_id")
        .annotate(last_checked_at=Max("last_reconciled_at"))
        .order_by(
            F("last_checked_at").asc(nulls_first=True),
            "message__channel_id",
            "dingtalk_task_id",
        )[:NOTIFY_RECONCILE_TASK_LIMIT],
    )
    typed = cast("list[dict[str, object]]", raw_tasks)
    tasks: list[tuple[int, str]] = []
    for row in typed:
        channel_id = row.get("message__channel_id")
        task_id = row.get("dingtalk_task_id")
        if isinstance(channel_id, int) and isinstance(task_id, str):
            tasks.append((channel_id, task_id))
    return tasks


def _mark_task_reconciled(*, channel_id: int, task_id: str, checked_at: datetime) -> None:
    _ = NotifyRecipient.objects.filter(
        message__channel_id=channel_id,
        dingtalk_task_id=task_id,
    ).update(last_reconciled_at=checked_at, error="", updated_at=checked_at)


def _mark_task_reconcile_failed(
    *,
    channel_id: int,
    task_id: str,
    checked_at: datetime,
    error: str,
) -> None:
    _ = NotifyRecipient.objects.filter(
        message__channel_id=channel_id,
        dingtalk_task_id=task_id,
    ).update(
        error=error[:NOTIFY_ERROR_MAX_CHARS],
        updated_at=checked_at,
    )


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
    progress = _send_progress(client.get_send_progress(agent_id=agent_id, task_id=task_id))
    if progress.status != DINGTALK_PROGRESS_DONE:
        return None
    return _send_result(client.get_send_result(agent_id=agent_id, task_id=task_id))


def _send_progress(raw: object) -> DingTalkSendProgress:
    if isinstance(raw, DingTalkSendProgress):
        return raw
    if not isinstance(raw, dict):
        message = "钉钉发送进度响应类型无效。"
        raise DingTalkApiRequestError(message)
    payload = cast("dict[str, object]", raw)
    status = payload.get("status")
    if isinstance(status, bool) or not isinstance(status, int):
        message = "钉钉发送进度 status 缺失或类型无效。"
        raise DingTalkApiRequestError(message)
    return DingTalkSendProgress(status=status)


def _send_result(raw: object) -> DingTalkSendResult:
    if isinstance(raw, DingTalkSendResult):
        return raw
    if not isinstance(raw, dict):
        message = "钉钉发送结果响应类型无效。"
        raise DingTalkApiRequestError(message)
    payload = cast("dict[str, object]", raw)
    return DingTalkSendResult(
        invalid_user_ids=_required_userid_set(payload, "invalid_user_id_list"),
        failed_user_ids=_required_userid_set(payload, "failed_user_id_list"),
        forbidden_user_ids=_required_userid_set(payload, "forbidden_user_id_list"),
        read_user_ids=_required_userid_set(payload, "read_user_id_list"),
        unread_user_ids=_required_userid_set(payload, "unread_user_id_list"),
        forbidden_receipts=_required_forbidden_receipts(payload),
    )


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


def _required_userid_set(payload: dict[str, object], field: str) -> frozenset[str]:
    raw = payload.get(field)
    if not isinstance(raw, list):
        message = f"钉钉发送结果 {field} 缺失或类型无效。"
        raise DingTalkApiRequestError(message)
    userids: set[str] = set()
    for item in cast("list[object]", raw):
        if not isinstance(item, str) or not item:
            message = f"钉钉发送结果 {field} 包含无效 userid。"
            raise DingTalkApiRequestError(message)
        userids.add(item)
    return frozenset(userids)


def _required_forbidden_receipts(
    payload: dict[str, object],
) -> tuple[DingTalkForbiddenReceipt, ...]:
    raw = payload.get("forbidden_list")
    if not isinstance(raw, list):
        message = "钉钉发送结果 forbidden_list 缺失或类型无效。"
        raise DingTalkApiRequestError(message)
    receipts: list[DingTalkForbiddenReceipt] = []
    for raw_item in cast("list[object]", raw):
        if not isinstance(raw_item, dict):
            message = "钉钉发送结果 forbidden_list 包含无效条目。"
            raise DingTalkApiRequestError(message)
        item = cast("dict[str, object]", raw_item)
        userid = item.get("userid")
        if not isinstance(userid, str) or not userid:
            message = "钉钉发送结果 forbidden_list 条目缺少 userid。"
            raise DingTalkApiRequestError(message)
        receipts.append(
            DingTalkForbiddenReceipt(
                userid=userid,
                code=_parse_forbidden_receipt_code(item.get("code")),
            ),
        )
    return tuple(receipts)


def _parse_forbidden_receipt_code(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        message = "钉钉发送结果 forbidden_list code 类型无效。"
        raise DingTalkApiRequestError(message)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    message = "钉钉发送结果 forbidden_list code 类型无效。"
    raise DingTalkApiRequestError(message)


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
