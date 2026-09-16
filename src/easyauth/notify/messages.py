from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from easyauth.notify.contracts import (
    APP_DISPLAY_NAME_TOO_LONG_MESSAGE,
    AUTHOR_TOO_LONG_MESSAGE,
    BIZ_TAG_TOO_LONG_MESSAGE,
    CONTENT_REQUIRED_MESSAGE,
    DEDUP_KEY_TOO_LONG_MESSAGE,
    DEEPLINK_URL_INVALID_MESSAGE,
    DINGTALK_LINK_PREFIX,
    FIELDS_INVALID_MESSAGE,
    HTTPS_PREFIX,
    NOTIFY_APP_DISPLAY_NAME_MAX_CHARS,
    NOTIFY_AUTHOR_MAX_CHARS,
    NOTIFY_BIZ_TAG_MAX_CHARS,
    NOTIFY_DEDUP_KEY_MAX_CHARS,
    NOTIFY_DEEPLINK_URL_MAX_CHARS,
    NOTIFY_FORM_FIELD_MAX_ITEMS,
    NOTIFY_FORM_KEY_MAX_CHARS,
    NOTIFY_FORM_VALUE_MAX_CHARS,
    NOTIFY_TITLE_MAX_CHARS,
    TITLE_REQUIRED_MESSAGE,
    TITLE_TOO_LONG_MESSAGE,
    NotifyAcceptError,
)
from easyauth.notify.head import resolve_notify_head
from easyauth.notify.oa import OaBuildInput, build_oa_msg

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.applications.models import App


@dataclass(frozen=True, slots=True)
class DingTalkMsgSource:
    title: str
    content: str
    deeplink_url: str = ""
    fields: tuple[tuple[str, str], ...] = ()
    app_display_name: str = ""
    author: str = ""


def build_dingtalk_msg(
    *,
    app: App,
    source: DingTalkMsgSource,
    sent_at: datetime | None = None,
) -> dict[str, object]:
    """组装钉钉工作通知 OA msg JSON(不含字节校验)。"""
    head_text, head_bgcolor = resolve_notify_head(
        app=app,
        app_display_name=source.app_display_name,
    )
    return build_oa_msg(
        OaBuildInput(
            title=source.title,
            content=source.content,
            head_text=head_text,
            head_bgcolor=head_bgcolor,
            deeplink_url=source.deeplink_url,
            fields=source.fields,
            author=source.author,
            sent_at=sent_at,
        ),
    )


def dingtalk_msg_utf8_size(msg: dict[str, object]) -> int:
    raw = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return len(raw)


@dataclass(frozen=True, slots=True)
class NotifyMessageInput:
    """通知正文输入: 受理校验、幂等哈希与落库共用同一字段集。"""

    content: str
    title: str
    deeplink_url: str = ""
    dedup_key: str = ""
    biz_tag: str = ""
    recipients: tuple[str, ...] = ()
    fields: tuple[tuple[str, str], ...] = ()
    app_display_name: str = ""
    author: str = ""


def compute_payload_hash(message: NotifyMessageInput) -> str:
    """按契约对规范化字段全集做幂等哈希。"""
    canonical = json.dumps(
        {
            "title": message.title,
            "content": message.content,
            "deeplink_url": message.deeplink_url,
            "biz_tag": message.biz_tag,
            "recipients": sorted(message.recipients),
            "fields": [{"key": key, "value": value} for key, value in message.fields],
            "app_display_name": message.app_display_name,
            "author": message.author,
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class NormalizedInput:
    title: str
    content: str
    deeplink_url: str
    dedup_key: str
    biz_tag: str
    fields: tuple[tuple[str, str], ...]
    app_display_name: str
    author: str


def normalize_and_validate(message: NotifyMessageInput) -> NormalizedInput:
    _validate_common_fields(message)
    deeplink_url = _validated_deeplink(message.deeplink_url)
    return NormalizedInput(
        title=message.title,
        content=message.content,
        deeplink_url=deeplink_url,
        dedup_key=message.dedup_key,
        biz_tag=message.biz_tag,
        fields=message.fields,
        app_display_name=message.app_display_name,
        author=message.author,
    )


def _validate_common_fields(message: NotifyMessageInput) -> None:
    if not message.content:
        raise NotifyAcceptError(
            kind="validation_error",
            message=CONTENT_REQUIRED_MESSAGE,
            field="content",
        )
    if not message.title:
        raise NotifyAcceptError(
            kind="validation_error",
            message=TITLE_REQUIRED_MESSAGE,
            field="title",
        )
    if len(message.title) > NOTIFY_TITLE_MAX_CHARS:
        raise NotifyAcceptError(
            kind="validation_error",
            message=TITLE_TOO_LONG_MESSAGE,
            field="title",
        )
    _validate_length_fields(message)
    _validate_form_fields(message.fields)


def _validate_length_fields(message: NotifyMessageInput) -> None:
    if len(message.dedup_key) > NOTIFY_DEDUP_KEY_MAX_CHARS:
        raise NotifyAcceptError(
            kind="validation_error",
            message=DEDUP_KEY_TOO_LONG_MESSAGE,
            field="dedup_key",
        )
    if len(message.biz_tag) > NOTIFY_BIZ_TAG_MAX_CHARS:
        raise NotifyAcceptError(
            kind="validation_error",
            message=BIZ_TAG_TOO_LONG_MESSAGE,
            field="biz_tag",
        )
    if len(message.app_display_name) > NOTIFY_APP_DISPLAY_NAME_MAX_CHARS:
        raise NotifyAcceptError(
            kind="validation_error",
            message=APP_DISPLAY_NAME_TOO_LONG_MESSAGE,
            field="app_display_name",
        )
    if len(message.author) > NOTIFY_AUTHOR_MAX_CHARS:
        raise NotifyAcceptError(
            kind="validation_error",
            message=AUTHOR_TOO_LONG_MESSAGE,
            field="author",
        )


def _validate_form_fields(fields: tuple[tuple[str, str], ...]) -> None:
    if len(fields) > NOTIFY_FORM_FIELD_MAX_ITEMS:
        raise NotifyAcceptError(
            kind="validation_error",
            message=FIELDS_INVALID_MESSAGE,
            field="fields",
        )
    for key, value in fields:
        if not key or len(key) > NOTIFY_FORM_KEY_MAX_CHARS:
            raise NotifyAcceptError(
                kind="validation_error",
                message=FIELDS_INVALID_MESSAGE,
                field="fields",
            )
        if len(value) > NOTIFY_FORM_VALUE_MAX_CHARS:
            raise NotifyAcceptError(
                kind="validation_error",
                message=FIELDS_INVALID_MESSAGE,
                field="fields",
            )


def _validated_deeplink(url: str) -> str:
    if not url:
        return ""
    if not _is_valid_deeplink_url(url):
        raise NotifyAcceptError(
            kind="validation_error",
            message=DEEPLINK_URL_INVALID_MESSAGE,
            field="deeplink_url",
        )
    return url


def _is_valid_deeplink_url(url: str) -> bool:
    if len(url) > NOTIFY_DEEPLINK_URL_MAX_CHARS:
        return False
    if url.startswith(HTTPS_PREFIX):
        return _valid_https_authority(url)
    if url.startswith(DINGTALK_LINK_PREFIX):
        return _is_valid_dingtalk_deeplink(url)
    return False


_TCP_PORT_MIN = 1
_TCP_PORT_MAX = 65535


def _valid_https_authority(url: str) -> bool:
    """拒绝含空白或控制字符的 https URL, 并要求主机名与合法端口。"""
    if any(ch.isspace() or not ch.isprintable() for ch in url):
        return False
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.netloc or not hostname:
        return False
    if port is None:
        return True
    return _TCP_PORT_MIN <= port <= _TCP_PORT_MAX


def _is_valid_dingtalk_deeplink(url: str) -> bool:
    # dingtalk:// 协议链内嵌 url 参数仍须为含主机名的 https URL。
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    embedded = query.get("url", [""])[0]
    return _valid_https_authority(embedded)
