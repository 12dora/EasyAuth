from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

from easyauth.accounts.directory_references import (
    AmbiguousDirectoryReferenceError,
    InvalidDirectoryReferenceError,
    resolve_directory_user,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.capabilities import app_capability_config
from easyauth.applications.models import CAPABILITY_NOTIFY, AppNotificationChannel
from easyauth.notify.contracts import (
    ACCEPT_TIME_ERROR_CODES,
    DAILY_QUOTA_EXCEEDED_MESSAGE,
    DEFAULT_DAILY_RECIPIENT_QUOTA,
    DINGTALK_USER_STATUS_ACTIVE,
    NOTIFY_ERROR_NO_DINGTALK_ID,
    NOTIFY_ERROR_USER_AMBIGUOUS,
    NOTIFY_ERROR_USER_INACTIVE,
    NOTIFY_ERROR_USER_NOT_FOUND,
    NOTIFY_ERROR_USER_SCOPE_MISMATCH,
    NOTIFY_MAX_RECIPIENTS,
    NOTIFY_MIN_RECIPIENTS,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_PENDING,
    RAW_REF_TOO_LONG_MESSAGE,
    RECIPIENTS_REQUIRED_MESSAGE,
    SHANGHAI_TZ,
    NotifyAcceptError,
    ResolvedRecipient,
)
from easyauth.notify.models import NOTIFY_RAW_REF_MAX_CHARS, NotifyMessage, NotifyRecipient

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime


def resolve_recipients(raw_refs: Sequence[str]) -> list[ResolvedRecipient]:
    """解析并按目录作用域 + userid 去重; 解析失败不阻塞, 直接成为 failed 候选。"""
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


def accept_time_rejected_count(message: NotifyMessage) -> int:
    return NotifyRecipient.objects.filter(
        message=message,
        status=NOTIFY_RECIPIENT_STATUS_FAILED,
        error_code__in=ACCEPT_TIME_ERROR_CODES,
    ).count()


def _resolve_one_recipient(raw_ref: str) -> ResolvedRecipient:
    preferred_user = UserMirror.objects.filter(authentik_user_id=raw_ref).first()
    if preferred_user is not None and not preferred_user.dingtalk_userid:
        return _failed_recipient(
            FailedRecipientInput(
                raw_ref=raw_ref,
                user=preferred_user,
                error_code=NOTIFY_ERROR_NO_DINGTALK_ID,
                error="用户存在但无钉钉绑定。",
            ),
        )
    try:
        mirror = resolve_directory_user(raw_ref)
    except AmbiguousDirectoryReferenceError:
        return _failed_recipient(
            FailedRecipientInput(
                raw_ref=raw_ref,
                user=preferred_user,
                error_code=NOTIFY_ERROR_USER_AMBIGUOUS,
                error="用户引用匹配多个企业目录用户, 必须使用 scoped 引用。",
            ),
        )
    except InvalidDirectoryReferenceError:
        return _failed_recipient(
            FailedRecipientInput(
                raw_ref=raw_ref,
                user=preferred_user,
                error_code=NOTIFY_ERROR_USER_NOT_FOUND,
                error="用户引用格式无效。",
            ),
        )
    if mirror is None:
        return _failed_recipient(
            FailedRecipientInput(
                raw_ref=raw_ref,
                user=preferred_user,
                error_code=NOTIFY_ERROR_USER_NOT_FOUND,
                error="用户引用无法解析到目录用户。",
            ),
        )
    if mirror.status != DINGTALK_USER_STATUS_ACTIVE:
        status_label = mirror.status or "unknown"
        return _failed_recipient(
            FailedRecipientInput(
                raw_ref=raw_ref,
                user=preferred_user
                or _lookup_user_mirror(mirror.source_slug, mirror.corp_id, mirror.user_id),
                dingtalk_source_slug=mirror.source_slug,
                dingtalk_corp_id=mirror.corp_id,
                dingtalk_userid=mirror.user_id,
                error_code=NOTIFY_ERROR_USER_INACTIVE,
                error=f"目录状态为 {status_label}, 拒绝投递。",
            ),
        )
    user = preferred_user or _lookup_user_mirror(mirror.source_slug, mirror.corp_id, mirror.user_id)
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


def enforce_channel_scope(
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


def _lookup_user_mirror(
    source_slug: str,
    corp_id: str,
    dingtalk_userid: str,
) -> UserMirror | None:
    if not source_slug:
        return None
    rows = list(
        UserMirror.objects.filter(
            dingtalk_source_slug=source_slug,
            dingtalk_corp_id=corp_id,
            dingtalk_userid=dingtalk_userid,
        ).order_by("authentik_user_id")[:2],
    )
    if len(rows) > 1:
        raise NotifyAcceptError(
            kind="validation_error",
            message=("钉钉身份绑定不唯一, 必须先修复 UserMirror 与目录来源作用域的绑定事实。"),
            field="recipients",
        )
    return rows[0] if rows else None


@dataclass(frozen=True, slots=True)
class FailedRecipientInput:
    """解析失败的收件人字段全集。"""

    raw_ref: str
    error_code: str
    error: str
    user: UserMirror | None = None
    dingtalk_source_slug: str = ""
    dingtalk_corp_id: str = ""
    dingtalk_userid: str = ""


def _failed_recipient(failed: FailedRecipientInput) -> ResolvedRecipient:
    return ResolvedRecipient(
        raw_ref=failed.raw_ref,
        user=failed.user,
        dingtalk_source_slug=failed.dingtalk_source_slug,
        dingtalk_corp_id=failed.dingtalk_corp_id,
        dingtalk_userid=failed.dingtalk_userid,
        status=NOTIFY_RECIPIENT_STATUS_FAILED,
        error_code=failed.error_code,
        error=failed.error,
    )


def assert_daily_quota(*, app_id: int, additional: int) -> None:
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
