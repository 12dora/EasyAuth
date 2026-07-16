from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Literal, cast, override
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Max, Q
from django.utils import timezone

from easyauth.accounts.directory_references import (
    AmbiguousDirectoryReferenceError,
    InvalidDirectoryReferenceError,
    resolve_directory_user,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.capabilities import app_capability_config
from easyauth.applications.models import CAPABILITY_NOTIFY, App, AppNotificationChannel
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.integrations.dingtalk.api_client import (
    DingTalkApiClient,
    DingTalkApiRequestError,
    DingTalkApiUnavailableError,
    DingTalkNotConfiguredError,
)
from easyauth.notify.models import (
    NOTIFY_ERROR_DINGTALK_DAILY_LIMIT,
    NOTIFY_ERROR_DINGTALK_DUPLICATE,
    NOTIFY_ERROR_DINGTALK_REJECTED,
    NOTIFY_ERROR_EXHAUSTED,
    NOTIFY_ERROR_NO_DINGTALK_ID,
    NOTIFY_ERROR_USER_AMBIGUOUS,
    NOTIFY_ERROR_USER_INACTIVE,
    NOTIFY_ERROR_USER_NOT_FOUND,
    NOTIFY_ERROR_USER_SCOPE_MISMATCH,
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
    NOTIFY_TEMPLATE_ACTION_CARD,
    NOTIFY_TEMPLATE_MARKDOWN,
    NOTIFY_TEMPLATE_TEXT,
    NOTIFY_TEMPLATE_VALUES,
    NotifyMessage,
    NotifyRecipient,
)
from easyauth.outbox.services import enqueue_task

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from uuid import UUID

type NotifyAcceptErrorKind = Literal[
    "conflict",
    "dependency_unavailable",
    "throttled",
    "validation_error",
]

logger = logging.getLogger(__name__)

DINGTALK_REF_PREFIX: Final = "dt:"
NOTIFY_DELIVERY_TASK_NAME: Final = "easyauth.notify.deliver_message"
NOTIFY_RECONCILE_TASK_NAME: Final = "easyauth.notify.reconcile_send_results"
NOTIFY_PRUNE_TASK_NAME: Final = "easyauth.notify.prune_messages"
NOTIFY_MSG_MAX_BYTES: Final = 2048
NOTIFY_MAX_RECIPIENTS: Final = 500
NOTIFY_MIN_RECIPIENTS: Final = 1
NOTIFY_TITLE_MAX_CHARS: Final = 100
NOTIFY_DEEPLINK_URL_MAX_CHARS: Final = 500
NOTIFY_DEEPLINK_TITLE_MAX_CHARS: Final = 20
NOTIFY_DEDUP_KEY_MAX_CHARS: Final = 128
NOTIFY_BIZ_TAG_MAX_CHARS: Final = 64
NOTIFY_RAW_REF_MAX_CHARS: Final = 200
DEFAULT_DEEPLINK_TITLE: Final = "查看详情"
DEFAULT_DAILY_RECIPIENT_QUOTA: Final = 5000
SHANGHAI_TZ: Final = ZoneInfo("Asia/Shanghai")
HTTPS_PREFIX: Final = "https://"
DINGTALK_LINK_PREFIX: Final = "dingtalk://dingtalkclient/page/link?"
DINGTALK_USER_STATUS_ACTIVE: Final = "active"

# 投递管道常量(第 3 篇 §1/§3/§4/§5/§6)
NOTIFY_RETRY_DELAYS_SECONDS: Final[tuple[int, ...]] = (60, 300, 1800, 7200)
NOTIFY_THROTTLE_RETRY_SECONDS: Final = 120
NOTIFY_MAX_CHUNKS_PER_RUN: Final = 5
NOTIFY_BATCH_SIZE: Final = 100
NOTIFY_LEASE_SECONDS: Final = 45
NOTIFY_ERROR_MAX_CHARS: Final = 500
NOTIFY_RECONCILE_WINDOW_HOURS: Final = 24
NOTIFY_RECONCILE_TASK_LIMIT: Final = 50
NOTIFY_PRUNE_BATCH_SIZE: Final = 500
DEFAULT_RETENTION_DAYS: Final = 180
DINGTALK_PROGRESS_DONE: Final = 2
# 调用级频控 errcode(第 4 篇 §4): QPS 90018, QPM 人次 143103/143104。
DINGTALK_THROTTLE_ERRCODES: Final[frozenset[int]] = frozenset({90018, 143103, 143104})
# 受理期解析失败集合: 幂等重放时 recipient_rejected 只计这些(契约 §N2)。
ACCEPT_TIME_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        NOTIFY_ERROR_USER_NOT_FOUND,
        NOTIFY_ERROR_NO_DINGTALK_ID,
        NOTIFY_ERROR_USER_INACTIVE,
        NOTIFY_ERROR_USER_AMBIGUOUS,
        NOTIFY_ERROR_USER_SCOPE_MISMATCH,
    },
)
MAX_DELIVERY_ATTEMPTS: Final = len(NOTIFY_RETRY_DELAYS_SECONDS) + 1

IDEMPOTENCY_PAYLOAD_CONFLICT_MESSAGE: Final = "同一 dedup_key 已使用不同的通知载荷。"
DAILY_QUOTA_EXCEEDED_MESSAGE: Final = "通知每日收件人配额已用尽。"
RECIPIENTS_REQUIRED_MESSAGE: Final = "recipients 必须为 1~500 个用户引用。"
TEMPLATE_INVALID_MESSAGE: Final = "template 必须是 text / markdown / action_card 之一。"
TITLE_REQUIRED_MESSAGE: Final = "markdown 与 action_card 模板必须提供 title。"
TITLE_TOO_LONG_MESSAGE: Final = "title 不得超过 100 字符。"
CONTENT_REQUIRED_MESSAGE: Final = "content 不能为空。"
DEEPLINK_REQUIRED_MESSAGE: Final = "action_card 模板必须提供 deeplink_url。"
DEEPLINK_URL_INVALID_MESSAGE: Final = (
    "deeplink_url 须以 https:// 或 dingtalk://dingtalkclient/page/link? 开头, 且长度 ≤500。"
)
DEEPLINK_TITLE_TOO_LONG_MESSAGE: Final = "deeplink_title 不得超过 20 字符。"
DEDUP_KEY_TOO_LONG_MESSAGE: Final = "dedup_key 不得超过 128 字符。"
BIZ_TAG_TOO_LONG_MESSAGE: Final = "biz_tag 不得超过 64 字符。"
MSG_TOO_LARGE_MESSAGE: Final = "组装后的钉钉 msg JSON 超过 2048 字节上限。"
RAW_REF_TOO_LONG_MESSAGE: Final = "收件人引用不得超过 200 字符。"
DINGTALK_AGENT_MISSING_MESSAGE: Final = "钉钉工作通知 agent_id 未配置。"
NOTIFY_CHANNEL_MISSING_MESSAGE: Final = "应用未配置可用的钉钉通知通道。"


@dataclass(frozen=True, slots=True)
class NotifyAcceptError(Exception):
    kind: NotifyAcceptErrorKind
    message: str
    field: str = ""
    retry_after_seconds: int | None = None

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class AcceptNotifyResult:
    message: NotifyMessage
    accepted: bool
    recipient_total: int
    recipient_rejected: int


@dataclass(frozen=True, slots=True)
class ResolvedRecipient:
    raw_ref: str
    user: UserMirror | None
    dingtalk_corp_id: str
    dingtalk_source_slug: str
    dingtalk_userid: str
    status: str
    error_code: str
    error: str


def build_dingtalk_msg(
    *,
    template: str,
    title: str,
    content: str,
    deeplink_url: str = "",
    deeplink_title: str = DEFAULT_DEEPLINK_TITLE,
) -> dict[str, object]:
    """组装钉钉工作通知 msg JSON 结构(不含字节校验)。"""
    if template == NOTIFY_TEMPLATE_TEXT:
        return {"msgtype": "text", "text": {"content": content}}
    if template == NOTIFY_TEMPLATE_MARKDOWN:
        return {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": content},
        }
    if template == NOTIFY_TEMPLATE_ACTION_CARD:
        button_title = deeplink_title or DEFAULT_DEEPLINK_TITLE
        return {
            "msgtype": "action_card",
            "action_card": {
                "title": title,
                "markdown": content,
                "single_title": button_title,
                "single_url": deeplink_url,
            },
        }
    raise NotifyAcceptError(
        kind="validation_error",
        message=TEMPLATE_INVALID_MESSAGE,
        field="template",
    )


def dingtalk_msg_utf8_size(msg: dict[str, object]) -> int:
    raw = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return len(raw)


def compute_payload_hash(  # noqa: PLR0913 - 幂等 hash 规范化字段全集(契约 §N2)。
    *,
    template: str,
    title: str,
    content: str,
    deeplink_url: str,
    deeplink_title: str,
    recipients: Sequence[str],
) -> str:
    canonical = json.dumps(
        {
            "template": template,
            "title": title,
            "content": content,
            "deeplink_url": deeplink_url,
            "deeplink_title": deeplink_title,
            "recipients": sorted(recipients),
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_recipients(raw_refs: Sequence[str]) -> list[ResolvedRecipient]:
    """解析并按钉钉 userid 合并去重; 解析失败不阻塞, 直接成为 failed 候选。"""
    if not (NOTIFY_MIN_RECIPIENTS <= len(raw_refs) <= NOTIFY_MAX_RECIPIENTS):
        raise NotifyAcceptError(
            kind="validation_error",
            message=RECIPIENTS_REQUIRED_MESSAGE,
            field="recipients",
        )
    for raw_ref in raw_refs:
        if not raw_ref:
            raise NotifyAcceptError(
                kind="validation_error",
                message=RECIPIENTS_REQUIRED_MESSAGE,
                field="recipients",
            )
        if len(raw_ref) > NOTIFY_RAW_REF_MAX_CHARS:
            raise NotifyAcceptError(
                kind="validation_error",
                message=RAW_REF_TOO_LONG_MESSAGE,
                field="recipients",
            )

    resolved: list[ResolvedRecipient] = []
    seen_directory_users: set[tuple[str, str, str]] = set()
    for raw_ref in raw_refs:
        item = _resolve_one_recipient(raw_ref)
        directory_key = (
            item.dingtalk_source_slug,
            item.dingtalk_corp_id,
            item.dingtalk_userid,
        )
        if item.dingtalk_userid and directory_key in seen_directory_users:
            continue
        if item.dingtalk_userid:
            seen_directory_users.add(directory_key)
        resolved.append(item)
    return resolved


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
    normalized = _normalize_and_validate(
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
                recipient_rejected=_accept_time_rejected_count(existing),
            )

    channel = _active_notification_channel(app.id)
    if channel is None:
        raise NotifyAcceptError(
            kind="dependency_unavailable",
            message=NOTIFY_CHANNEL_MISSING_MESSAGE,
        )
    resolved = _enforce_channel_scope(channel, resolved)

    try:
        with transaction.atomic():
            locked_app = App.objects.select_for_update().get(id=app.id)
            # 日配额: 事务内先查后写(第 2 篇 §3.2)。
            _assert_daily_quota(app_id=locked_app.id, additional=len(resolved))
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
            recipient_rejected=_accept_time_rejected_count(winner),
        )

    rejected = sum(1 for item in resolved if item.status == NOTIFY_RECIPIENT_STATUS_FAILED)
    return AcceptNotifyResult(
        message=message,
        accepted=True,
        recipient_total=len(resolved),
        recipient_rejected=rejected,
    )


def deliver_message(message_id: str, generation: int) -> None:
    """单条消息一轮投递: 抢租约 → 分批调钉钉 → 推进状态 → 排程下一轮或收敛。"""
    claimed = _claim_message(message_id)
    if claimed is None:
        return
    message = claimed.message
    claim_token = claimed.claim_token

    open_recipients = list(
        NotifyRecipient.objects.filter(
            message_id=message.id,
            status__in=(NOTIFY_RECIPIENT_STATUS_PENDING, NOTIFY_RECIPIENT_STATUS_THROTTLED),
        )
        .order_by("id")
        .all()[: NOTIFY_BATCH_SIZE * NOTIFY_MAX_CHUNKS_PER_RUN],
    )
    if not open_recipients:
        _refresh_and_maybe_finalize(message, claim_token=claim_token)
        return

    network_interrupted = False
    try:
        client, agent_id = _dingtalk_client_and_agent(message.channel)
    except (DingTalkNotConfiguredError, ValueError) as error:
        # 配置缺失视为可恢复: 保持 pending, 走常规退避; 健康探测补齐后自动恢复(第 3 篇 §8)。
        network_interrupted = True
        _ = NotifyMessage.objects.filter(id=message.id, claim_token=claim_token).update(
            last_error=str(error)[:NOTIFY_ERROR_MAX_CHARS],
        )
        _schedule_or_finalize(
            message,
            claim_token=claim_token,
            generation=generation,
            network_interrupted=True,
        )
        return

    msg = build_dingtalk_msg(
        template=message.template,
        title=message.title,
        content=message.content,
        deeplink_url=message.deeplink_url,
        deeplink_title=message.deeplink_title or DEFAULT_DEEPLINK_TITLE,
    )
    chunks = [
        open_recipients[i : i + NOTIFY_BATCH_SIZE]
        for i in range(0, len(open_recipients), NOTIFY_BATCH_SIZE)
    ]
    for chunk in chunks:
        userids = [row.dingtalk_userid for row in chunk if row.dingtalk_userid]
        if not userids:
            continue
        try:
            task_id = client.send_work_notification(
                agent_id=agent_id,
                userid_list=userids,
                msg=msg,
            )
        except DingTalkApiUnavailableError as error:
            network_interrupted = True
            _ = NotifyMessage.objects.filter(id=message.id, claim_token=claim_token).update(
                last_error=str(error)[:NOTIFY_ERROR_MAX_CHARS],
            )
            break
        except DingTalkApiRequestError as error:
            if error.errcode is not None and error.errcode in DINGTALK_THROTTLE_ERRCODES:
                _mark_chunk_throttled(chunk, error=str(error)[:NOTIFY_ERROR_MAX_CHARS])
                continue
            if _is_retryable_request_error(error):
                # 钉钉 5xx / 无业务 errcode 的 HTTP 层故障: 保持原状态, 常规退避(第 3 篇 §4)。
                network_interrupted = True
                _ = NotifyMessage.objects.filter(id=message.id, claim_token=claim_token).update(
                    last_error=str(error)[:NOTIFY_ERROR_MAX_CHARS],
                )
                break
            _fail_open_recipients(
                chunk,
                error_code=NOTIFY_ERROR_DINGTALK_REJECTED,
                error=str(error)[:NOTIFY_ERROR_MAX_CHARS],
            )
            continue
        _mark_chunk_sent(chunk, task_id=task_id)

    message.refresh_from_db()
    _refresh_message_counts(message)
    message.refresh_from_db()
    _schedule_or_finalize(
        message,
        claim_token=claim_token,
        generation=generation,
        network_interrupted=network_interrupted,
    )


def reconcile_send_results() -> int:
    """对 sent 收件人按 task_id 查钉钉回执, 升级 delivered/failed。返回处理的 task 数。"""
    if not getattr(settings, "EASYAUTH_NOTIFY_RECONCILE_ENABLED", True):
        return 0

    now = timezone.now()
    window_start = now - timedelta(hours=NOTIFY_RECONCILE_WINDOW_HOURS)

    channel_tasks = select_reconcile_tasks(window_start)
    if not channel_tasks:
        return 0

    processed = 0
    affected_message_ids: set[UUID] = set()
    for channel_id, task_id in channel_tasks:
        channel = AppNotificationChannel.objects.filter(id=channel_id).first()
        if channel is None:
            _mark_task_reconciled(channel_id=channel_id, task_id=task_id, checked_at=now)
            continue
        try:
            client, agent_id = _dingtalk_client_and_agent(channel)
        except (DingTalkNotConfiguredError, ValueError):
            _mark_task_reconciled(channel_id=channel_id, task_id=task_id, checked_at=now)
            continue
        mids = _reconcile_one_task(
            client=client,
            agent_id=agent_id,
            channel_id=channel_id,
            task_id=task_id,
            now=now,
        )
        _mark_task_reconciled(channel_id=channel_id, task_id=task_id, checked_at=now)
        if not mids:
            continue
        affected_message_ids.update(mids)
        processed += 1

    for mid in affected_message_ids:
        msg = NotifyMessage.objects.filter(id=mid).first()
        if msg is not None:
            _refresh_message_counts(msg)
            _maybe_rewrite_aggregate_after_reconcile(msg)
    return processed


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
    ).update(last_reconciled_at=checked_at, updated_at=checked_at)


def _reconcile_one_task(
    *,
    client: DingTalkApiClient,
    agent_id: str | int,
    channel_id: int,
    task_id: str,
    now: datetime,
) -> set[UUID]:
    try:
        progress = client.get_send_progress(agent_id=agent_id, task_id=task_id)
    except (DingTalkApiRequestError, DingTalkApiUnavailableError):
        return set()
    status_raw = progress.get("status")
    if not isinstance(status_raw, (int, float)) or int(status_raw) != DINGTALK_PROGRESS_DONE:
        return set()
    try:
        send_result = client.get_send_result(agent_id=agent_id, task_id=task_id)
    except (DingTalkApiRequestError, DingTalkApiUnavailableError):
        return set()
    return _apply_send_result(
        channel_id=channel_id,
        task_id=task_id,
        send_result=send_result,
        now=now,
    )


def prune_messages() -> int:
    """按保留期分批删除历史消息(级联收件人)。返回删除的消息行数。"""
    retention_days = getattr(settings, "EASYAUTH_NOTIFY_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)
    if (
        not isinstance(retention_days, int)
        or isinstance(retention_days, bool)
        or retention_days < 1
    ):
        retention_days = DEFAULT_RETENTION_DAYS
    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted_messages = 0
    while True:
        batch_ids = list(
            NotifyMessage.objects.filter(created_at__lt=cutoff)
            .order_by("created_at")
            .values_list("id", flat=True)[:NOTIFY_PRUNE_BATCH_SIZE],
        )
        if not batch_ids:
            break
        deleted, _ = NotifyMessage.objects.filter(id__in=batch_ids).delete()
        # delete() 计数含级联 recipients; 消息数按 batch 计。
        deleted_messages += len(batch_ids)
        if deleted == 0:
            break
    return deleted_messages


def _accept_time_rejected_count(message: NotifyMessage) -> int:
    return NotifyRecipient.objects.filter(
        message=message,
        status=NOTIFY_RECIPIENT_STATUS_FAILED,
        error_code__in=ACCEPT_TIME_ERROR_CODES,
    ).count()


@dataclass(frozen=True, slots=True)
class _NormalizedInput:
    template: str
    title: str
    content: str
    deeplink_url: str
    deeplink_title: str
    dedup_key: str
    biz_tag: str


def _normalize_and_validate(  # noqa: PLR0913 - 受理字段全集。
    *,
    template: str,
    title: str,
    content: str,
    deeplink_url: str,
    deeplink_title: str,
    dedup_key: str,
    biz_tag: str,
) -> _NormalizedInput:
    _validate_common_fields(
        template=template,
        title=title,
        content=content,
        deeplink_title=deeplink_title,
        dedup_key=dedup_key,
        biz_tag=biz_tag,
    )
    effective_title, effective_deeplink, effective_deeplink_title = _template_fields(
        template=template,
        title=title,
        deeplink_url=deeplink_url,
        deeplink_title=deeplink_title,
    )
    return _NormalizedInput(
        template=template,
        title=effective_title,
        content=content,
        deeplink_url=effective_deeplink,
        deeplink_title=effective_deeplink_title,
        dedup_key=dedup_key,
        biz_tag=biz_tag,
    )


def _validate_common_fields(  # noqa: PLR0913
    *,
    template: str,
    title: str,
    content: str,
    deeplink_title: str,
    dedup_key: str,
    biz_tag: str,
) -> None:
    if template not in NOTIFY_TEMPLATE_VALUES:
        raise NotifyAcceptError(
            kind="validation_error",
            message=TEMPLATE_INVALID_MESSAGE,
            field="template",
        )
    if not content:
        raise NotifyAcceptError(
            kind="validation_error",
            message=CONTENT_REQUIRED_MESSAGE,
            field="content",
        )
    if len(title) > NOTIFY_TITLE_MAX_CHARS:
        raise NotifyAcceptError(
            kind="validation_error",
            message=TITLE_TOO_LONG_MESSAGE,
            field="title",
        )
    if len(dedup_key) > NOTIFY_DEDUP_KEY_MAX_CHARS:
        raise NotifyAcceptError(
            kind="validation_error",
            message=DEDUP_KEY_TOO_LONG_MESSAGE,
            field="dedup_key",
        )
    if len(biz_tag) > NOTIFY_BIZ_TAG_MAX_CHARS:
        raise NotifyAcceptError(
            kind="validation_error",
            message=BIZ_TAG_TOO_LONG_MESSAGE,
            field="biz_tag",
        )
    if len(deeplink_title) > NOTIFY_DEEPLINK_TITLE_MAX_CHARS:
        raise NotifyAcceptError(
            kind="validation_error",
            message=DEEPLINK_TITLE_TOO_LONG_MESSAGE,
            field="deeplink_title",
        )


def _template_fields(
    *,
    template: str,
    title: str,
    deeplink_url: str,
    deeplink_title: str,
) -> tuple[str, str, str]:
    if template == NOTIFY_TEMPLATE_TEXT:
        # text 模板忽略 title / deeplink。
        return "", "", DEFAULT_DEEPLINK_TITLE
    if template == NOTIFY_TEMPLATE_MARKDOWN:
        if not title:
            raise NotifyAcceptError(
                kind="validation_error",
                message=TITLE_REQUIRED_MESSAGE,
                field="title",
            )
        return title, "", DEFAULT_DEEPLINK_TITLE
    # action_card
    if not title:
        raise NotifyAcceptError(
            kind="validation_error",
            message=TITLE_REQUIRED_MESSAGE,
            field="title",
        )
    if not deeplink_url:
        raise NotifyAcceptError(
            kind="validation_error",
            message=DEEPLINK_REQUIRED_MESSAGE,
            field="deeplink_url",
        )
    if not _is_valid_deeplink_url(deeplink_url):
        raise NotifyAcceptError(
            kind="validation_error",
            message=DEEPLINK_URL_INVALID_MESSAGE,
            field="deeplink_url",
        )
    return title, deeplink_url, deeplink_title or DEFAULT_DEEPLINK_TITLE


def _is_valid_deeplink_url(url: str) -> bool:
    if len(url) > NOTIFY_DEEPLINK_URL_MAX_CHARS:
        return False
    if url.startswith(HTTPS_PREFIX):
        return len(url) > len(HTTPS_PREFIX)
    if url.startswith(DINGTALK_LINK_PREFIX):
        # dingtalk:// 协议链内嵌 url 参数仍须 https。
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        embedded = query.get("url", [""])[0]
        return bool(embedded.startswith(HTTPS_PREFIX) and len(embedded) > len(HTTPS_PREFIX))
    return False


def _resolve_one_recipient(raw_ref: str) -> ResolvedRecipient:
    preferred_user = (
        None
        if raw_ref.startswith(DINGTALK_REF_PREFIX)
        else UserMirror.objects.filter(authentik_user_id=raw_ref).first()
    )
    if preferred_user is not None and not preferred_user.dingtalk_userid:
        return _failed_recipient(
            raw_ref=raw_ref,
            user=preferred_user,
            error_code=NOTIFY_ERROR_NO_DINGTALK_ID,
            error="用户存在但无钉钉绑定。",
        )
    try:
        mirror = resolve_directory_user(raw_ref)
    except AmbiguousDirectoryReferenceError:
        return _failed_recipient(
            raw_ref=raw_ref,
            user=preferred_user,
            error_code=NOTIFY_ERROR_USER_AMBIGUOUS,
            error="用户引用匹配多个企业目录用户, 必须使用 scoped 引用。",
        )
    except InvalidDirectoryReferenceError:
        return _failed_recipient(
            raw_ref=raw_ref,
            user=preferred_user,
            error_code=NOTIFY_ERROR_USER_NOT_FOUND,
            error="用户引用格式无效。",
        )
    if mirror is None:
        return _failed_recipient(
            raw_ref=raw_ref,
            user=preferred_user,
            error_code=NOTIFY_ERROR_USER_NOT_FOUND,
            error="用户引用无法解析到目录用户。",
        )
    if mirror.status != DINGTALK_USER_STATUS_ACTIVE:
        status_label = mirror.status or "unknown"
        return _failed_recipient(
            raw_ref=raw_ref,
            user=preferred_user or _lookup_user_mirror(mirror.corp_id, mirror.user_id),
            dingtalk_source_slug=mirror.source_slug,
            dingtalk_corp_id=mirror.corp_id,
            dingtalk_userid=mirror.user_id,
            error_code=NOTIFY_ERROR_USER_INACTIVE,
            error=f"目录状态为 {status_label}, 拒绝投递。",
        )
    user = preferred_user or _lookup_user_mirror(mirror.corp_id, mirror.user_id)
    return ResolvedRecipient(
        raw_ref=raw_ref,
        user=user,
        dingtalk_source_slug=mirror.source_slug,
        dingtalk_corp_id=mirror.corp_id,
        dingtalk_userid=mirror.user_id,
        status=NOTIFY_RECIPIENT_STATUS_PENDING,
        error_code="",
        error="",
    )


def _enforce_channel_scope(
    channel: AppNotificationChannel,
    recipients: list[ResolvedRecipient],
) -> list[ResolvedRecipient]:
    scoped: list[ResolvedRecipient] = []
    for recipient in recipients:
        if recipient.status != NOTIFY_RECIPIENT_STATUS_PENDING:
            scoped.append(recipient)
            continue
        if (
            recipient.dingtalk_source_slug == channel.directory_source_slug
            and recipient.dingtalk_corp_id == channel.corp_id
        ):
            scoped.append(recipient)
            continue
        scoped.append(
            replace(
                recipient,
                status=NOTIFY_RECIPIENT_STATUS_FAILED,
                error_code=NOTIFY_ERROR_USER_SCOPE_MISMATCH,
                error="收件人不属于应用通知通道绑定的企业目录作用域。",
            ),
        )
    return scoped


def _lookup_user_mirror(corp_id: str, dingtalk_userid: str) -> UserMirror | None:
    return UserMirror.objects.filter(
        dingtalk_corp_id=corp_id,
        dingtalk_userid=dingtalk_userid,
    ).first()


def _failed_recipient(  # noqa: PLR0913 - 失败收件人字段全集。
    *,
    raw_ref: str,
    error_code: str,
    error: str,
    user: UserMirror | None = None,
    dingtalk_source_slug: str = "",
    dingtalk_corp_id: str = "",
    dingtalk_userid: str = "",
) -> ResolvedRecipient:
    return ResolvedRecipient(
        raw_ref=raw_ref,
        user=user,
        dingtalk_source_slug=dingtalk_source_slug,
        dingtalk_corp_id=dingtalk_corp_id,
        dingtalk_userid=dingtalk_userid,
        status=NOTIFY_RECIPIENT_STATUS_FAILED,
        error_code=error_code,
        error=error,
    )


def _assert_daily_quota(*, app_id: int, additional: int) -> None:
    quota = _daily_recipient_quota(app_id)
    day_start = _shanghai_day_start()
    used = NotifyRecipient.objects.filter(
        message__app_id=app_id,
        created_at__gte=day_start,
    ).count()
    if used + additional > quota:
        raise NotifyAcceptError(
            kind="throttled",
            message=DAILY_QUOTA_EXCEEDED_MESSAGE,
            retry_after_seconds=_seconds_until_next_shanghai_day(),
        )


def _daily_recipient_quota(app_id: int) -> int:
    config = app_capability_config(app_id, CAPABILITY_NOTIFY)
    raw = config.get("daily_recipient_quota")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    default = getattr(
        settings,
        "EASYAUTH_NOTIFY_DEFAULT_DAILY_RECIPIENT_QUOTA",
        DEFAULT_DAILY_RECIPIENT_QUOTA,
    )
    if isinstance(default, int) and not isinstance(default, bool) and default > 0:
        return default
    return DEFAULT_DAILY_RECIPIENT_QUOTA


def _shanghai_day_start() -> datetime:
    now_shanghai = timezone.now().astimezone(SHANGHAI_TZ)
    return now_shanghai.replace(hour=0, minute=0, second=0, microsecond=0)


def _seconds_until_next_shanghai_day() -> int:
    now_shanghai = timezone.now().astimezone(SHANGHAI_TZ)
    tomorrow = (now_shanghai + timedelta(days=1)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return max(1, int((tomorrow - now_shanghai).total_seconds()))


def _create_message_with_recipients(  # noqa: PLR0913 - 落库字段全集。
    *,
    app: App,
    channel: AppNotificationChannel,
    normalized: _NormalizedInput,
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
        recipient_failed=rejected if pending_count == 0 else 0,
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


def _active_notification_channel(app_id: int) -> AppNotificationChannel | None:
    return (
        AppNotificationChannel.objects.filter(app_id=app_id, is_active=True)
        .exclude(dingtalk_app_key="")
        .exclude(dingtalk_app_secret="")
        .exclude(agent_id="")
        .exclude(directory_source_slug="")
        .exclude(corp_id="")
        .first()
    )


def _dingtalk_client_and_agent(
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


def _refresh_message_counts(message: NotifyMessage) -> None:
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


def _open_recipient_counts(message_id: UUID) -> tuple[int, int]:
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
    pending, throttled = _open_recipient_counts(message.id)
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
    _refresh_message_counts(message)
    message.refresh_from_db()
    pending, throttled = _open_recipient_counts(message.id)
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
    _refresh_message_counts(message)
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


def _apply_send_result(
    *,
    channel_id: int,
    task_id: str,
    send_result: dict[str, object],
    now: datetime,
) -> set[UUID]:
    rejected_userids = _string_id_set(send_result.get("invalid_user_id_list")) | _string_id_set(
        send_result.get("failed_user_id_list"),
    )
    forbidden_by_code = _forbidden_userid_codes(send_result)
    delivered_userids = _string_id_set(send_result.get("read_user_id_list")) | _string_id_set(
        send_result.get("unread_user_id_list"),
    )
    for userid in _string_id_set(send_result.get("forbidden_user_id_list")):
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


def _string_id_set(raw: object) -> set[str]:
    if not isinstance(raw, list):
        return set()
    result: set[str] = set()
    for item in cast("list[object]", raw):
        if isinstance(item, str) and item:
            result.add(item)
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            result.add(str(int(item)))
    return result


def _forbidden_userid_codes(send_result: dict[str, object]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    raw = send_result.get("forbidden_list")
    if not isinstance(raw, list):
        return mapping
    for item_raw in cast("list[object]", raw):
        if not isinstance(item_raw, dict):
            continue
        item = cast("dict[str, object]", item_raw)
        userid_raw = item.get("userid")
        if not isinstance(userid_raw, str) or not userid_raw:
            continue
        code_int = _parse_forbidden_code(item.get("code"))
        if code_int == 143106:  # noqa: PLR2004 - 钉钉官方流控码。
            mapping[userid_raw] = NOTIFY_ERROR_DINGTALK_DUPLICATE
        elif code_int == 143105:  # noqa: PLR2004 - 钉钉官方流控码。
            mapping[userid_raw] = NOTIFY_ERROR_DINGTALK_DAILY_LIMIT
        else:
            mapping[userid_raw] = NOTIFY_ERROR_DINGTALK_REJECTED
    return mapping


def _parse_forbidden_code(code_raw: object) -> int | None:
    if isinstance(code_raw, bool):
        return None
    if isinstance(code_raw, (int, float)):
        return int(code_raw)
    if isinstance(code_raw, str) and code_raw.isdigit():
        return int(code_raw)
    return None


def _maybe_rewrite_aggregate_after_reconcile(message: NotifyMessage) -> None:
    """对账可能把 sent 改为 failed, 需把 completed 降为 partially_failed/failed。"""
    message.refresh_from_db()
    pending, throttled = _open_recipient_counts(message.id)
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
