from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Literal, override
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from easyauth.accounts.models import DingTalkUserMirror, UserMirror
from easyauth.applications.capabilities import app_capability_config
from easyauth.applications.models import CAPABILITY_NOTIFY
from easyauth.notify.models import (
    NOTIFY_ERROR_NO_DINGTALK_ID,
    NOTIFY_ERROR_USER_INACTIVE,
    NOTIFY_ERROR_USER_NOT_FOUND,
    NOTIFY_MESSAGE_STATUS_FAILED,
    NOTIFY_MESSAGE_STATUS_PENDING,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_PENDING,
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

    from easyauth.applications.models import App

type NotifyAcceptErrorKind = Literal[
    "conflict",
    "throttled",
    "validation_error",
]

DINGTALK_REF_PREFIX: Final = "dt:"
NOTIFY_DELIVERY_TASK_NAME: Final = "easyauth.notify.deliver_message"
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


def compute_payload_hash(
    *,
    template: str,
    title: str,
    content: str,
    deeplink_url: str,
    recipients: Sequence[str],
) -> str:
    canonical = json.dumps(
        {
            "template": template,
            "title": title,
            "content": content,
            "deeplink_url": deeplink_url,
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
    seen_dingtalk_userids: set[str] = set()
    for raw_ref in raw_refs:
        item = _resolve_one_recipient(raw_ref)
        if item.dingtalk_userid and item.dingtalk_userid in seen_dingtalk_userids:
            continue
        if item.dingtalk_userid:
            seen_dingtalk_userids.add(item.dingtalk_userid)
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
            rejected = NotifyRecipient.objects.filter(
                message=existing,
                status=NOTIFY_RECIPIENT_STATUS_FAILED,
            ).count()
            return AcceptNotifyResult(
                message=existing,
                accepted=False,
                recipient_total=existing.recipient_total,
                recipient_rejected=rejected,
            )

    try:
        with transaction.atomic():
            # 日配额: 事务内先查后写(第 2 篇 §3.2)。
            _assert_daily_quota(app_id=app.id, additional=len(resolved))
            message = _create_message_with_recipients(
                app=app,
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
        rejected = NotifyRecipient.objects.filter(
            message=winner,
            status=NOTIFY_RECIPIENT_STATUS_FAILED,
        ).count()
        return AcceptNotifyResult(
            message=winner,
            accepted=False,
            recipient_total=winner.recipient_total,
            recipient_rejected=rejected,
        )

    rejected = sum(1 for item in resolved if item.status == NOTIFY_RECIPIENT_STATUS_FAILED)
    return AcceptNotifyResult(
        message=message,
        accepted=True,
        recipient_total=len(resolved),
        recipient_rejected=rejected,
    )


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
    if raw_ref.startswith(DINGTALK_REF_PREFIX):
        dingtalk_userid = raw_ref[len(DINGTALK_REF_PREFIX) :]
        if not dingtalk_userid:
            return _failed_recipient(
                raw_ref=raw_ref,
                error_code=NOTIFY_ERROR_USER_NOT_FOUND,
                error="dt: 引用缺少钉钉 userid。",
            )
        return _resolve_by_dingtalk_userid(raw_ref=raw_ref, dingtalk_userid=dingtalk_userid)

    user = UserMirror.objects.filter(authentik_user_id=raw_ref).first()
    if user is None:
        return _failed_recipient(
            raw_ref=raw_ref,
            error_code=NOTIFY_ERROR_USER_NOT_FOUND,
            error="用户引用无法解析到目录用户。",
        )
    if not user.dingtalk_userid:
        return _failed_recipient(
            raw_ref=raw_ref,
            user=user,
            error_code=NOTIFY_ERROR_NO_DINGTALK_ID,
            error="用户存在但无钉钉绑定。",
        )
    return _resolve_by_dingtalk_userid(
        raw_ref=raw_ref,
        dingtalk_userid=user.dingtalk_userid,
        preferred_user=user,
        preferred_corp_id=user.dingtalk_corp_id,
    )


def _resolve_by_dingtalk_userid(
    *,
    raw_ref: str,
    dingtalk_userid: str,
    preferred_user: UserMirror | None = None,
    preferred_corp_id: str = "",
) -> ResolvedRecipient:
    mirror_qs = DingTalkUserMirror.objects.filter(user_id=dingtalk_userid)
    if preferred_corp_id:
        mirror = mirror_qs.filter(corp_id=preferred_corp_id).first() or mirror_qs.first()
    else:
        mirror = mirror_qs.first()
    if mirror is None:
        return _failed_recipient(
            raw_ref=raw_ref,
            user=preferred_user,
            dingtalk_corp_id=preferred_corp_id,
            dingtalk_userid=dingtalk_userid,
            error_code=NOTIFY_ERROR_USER_NOT_FOUND,
            error="用户引用无法解析到目录用户。",
        )
    if mirror.status != DINGTALK_USER_STATUS_ACTIVE:
        status_label = mirror.status or "unknown"
        return _failed_recipient(
            raw_ref=raw_ref,
            user=preferred_user or _lookup_user_mirror(mirror.corp_id, mirror.user_id),
            dingtalk_corp_id=mirror.corp_id,
            dingtalk_userid=mirror.user_id,
            error_code=NOTIFY_ERROR_USER_INACTIVE,
            error=f"目录状态为 {status_label}, 拒绝投递。",
        )
    user = preferred_user or _lookup_user_mirror(mirror.corp_id, mirror.user_id)
    return ResolvedRecipient(
        raw_ref=raw_ref,
        user=user,
        dingtalk_corp_id=mirror.corp_id,
        dingtalk_userid=mirror.user_id,
        status=NOTIFY_RECIPIENT_STATUS_PENDING,
        error_code="",
        error="",
    )


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
    dingtalk_corp_id: str = "",
    dingtalk_userid: str = "",
) -> ResolvedRecipient:
    return ResolvedRecipient(
        raw_ref=raw_ref,
        user=user,
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
        template=normalized.template,
        title=normalized.title,
        content=normalized.content,
        deeplink_url=normalized.deeplink_url,
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
