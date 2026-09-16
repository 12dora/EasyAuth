"""服务号机器人一对一投递(工作通知的 sidecar 通道)。

与工作通知彼此独立: 机器人结果只写收件人行的 robot_* 字段, 不改写工作通知状态;
只有工作通知渠道被全局关停时, 才由 `settle_from_robot_result` 用机器人结果推进收件人终态。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from django.utils import timezone

from easyauth.integrations.dingtalk.api_client import (
    DingTalkApiClient,
    DingTalkApiRequestError,
    DingTalkApiUnavailableError,
    DingTalkRobotOtoResult,
    chunk_robot_user_ids,
)
from easyauth.notify.contracts import (
    NOTIFY_ERROR_MAX_CHARS,
    NOTIFY_ERROR_ROBOT_REJECTED,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_PENDING,
    NOTIFY_RECIPIENT_STATUS_SENT,
    NOTIFY_RECIPIENT_STATUS_THROTTLED,
)
from easyauth.notify.models import (
    NOTIFY_ROBOT_STATUS_FAILED,
    NOTIFY_ROBOT_STATUS_SENT,
    NotifyRecipient,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

logger = logging.getLogger(__name__)

# 仅机器人投递时的失败说明; 每行的钉钉原始错误仍保留在 robot_error。
ROBOT_ONLY_DELIVERY_FAILED_MESSAGE: Final = "工作通知渠道已关闭, 服务号机器人投递失败。"

_OPEN_STATUSES: Final = (NOTIFY_RECIPIENT_STATUS_PENDING, NOTIFY_RECIPIENT_STATUS_THROTTLED)


@dataclass(frozen=True, slots=True)
class RobotDispatch:
    """一条消息在本轮投递中要发的机器人消息(客户端与正文在整轮内不变)。"""

    client: DingTalkApiClient
    message_id: UUID
    title: str
    text: str
    single_url: str


def send_robot_channel(dispatch: RobotDispatch, chunk: Sequence[NotifyRecipient]) -> None:
    pending = [row for row in chunk if row.dingtalk_userid and row.robot_status is None]
    if not pending:
        return
    by_userid = {row.dingtalk_userid: row for row in pending}
    userids = [row.dingtalk_userid for row in pending]
    for batch_ids in chunk_robot_user_ids(userids):
        _send_robot_batch(dispatch, by_userid, batch_ids)


def settle_from_robot_result(chunk: Sequence[NotifyRecipient]) -> None:
    """工作通知关闭时用机器人结果推进收件人状态, 否则收件人会一直挂到重试耗尽。

    机器人未尝试(robot_status 仍为空)的行保持原状态, 由常规退避继续处理。
    """
    rows = list(
        NotifyRecipient.objects.filter(
            id__in=[row.id for row in chunk],
            status__in=_OPEN_STATUSES,
        ).all(),
    )
    sent_ids = [row.id for row in rows if row.robot_status == NOTIFY_ROBOT_STATUS_SENT]
    failed_ids = [row.id for row in rows if row.robot_status == NOTIFY_ROBOT_STATUS_FAILED]
    now = timezone.now()
    if sent_ids:
        # 未经 OA 发送: dingtalk_task_id 留空, 对账任务据此跳过这些行。
        _ = NotifyRecipient.objects.filter(id__in=sent_ids, status__in=_OPEN_STATUSES).update(
            status=NOTIFY_RECIPIENT_STATUS_SENT,
            sent_at=now,
            error_code="",
            error="",
            updated_at=now,
        )
    if failed_ids:
        _ = NotifyRecipient.objects.filter(id__in=failed_ids, status__in=_OPEN_STATUSES).update(
            status=NOTIFY_RECIPIENT_STATUS_FAILED,
            error_code=NOTIFY_ERROR_ROBOT_REJECTED,
            error=ROBOT_ONLY_DELIVERY_FAILED_MESSAGE,
            updated_at=now,
        )


def _send_robot_batch(
    dispatch: RobotDispatch,
    by_userid: dict[str, NotifyRecipient],
    batch_ids: tuple[str, ...],
) -> None:
    recipients = tuple(by_userid[userid] for userid in batch_ids)
    try:
        results = dispatch.client.send_robot_oto_messages(
            robot_code=dispatch.client.app_key,
            user_ids=batch_ids,
            title=dispatch.title,
            text=dispatch.text,
            single_url=dispatch.single_url,
        )
    except (DingTalkApiUnavailableError, DingTalkApiRequestError) as error:
        logger.warning(
            "notify_robot_send_failed message_id=%s userids=%s error=%s",
            dispatch.message_id,
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
