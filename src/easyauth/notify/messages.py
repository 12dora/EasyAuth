from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from easyauth.notify.contracts import (
    BIZ_TAG_TOO_LONG_MESSAGE,
    CONTENT_REQUIRED_MESSAGE,
    DEDUP_KEY_TOO_LONG_MESSAGE,
    DEEPLINK_REQUIRED_MESSAGE,
    DEEPLINK_TITLE_TOO_LONG_MESSAGE,
    DEEPLINK_URL_INVALID_MESSAGE,
    DEFAULT_DEEPLINK_TITLE,
    DINGTALK_LINK_PREFIX,
    HTTPS_PREFIX,
    NOTIFY_BIZ_TAG_MAX_CHARS,
    NOTIFY_DEDUP_KEY_MAX_CHARS,
    NOTIFY_DEEPLINK_TITLE_MAX_CHARS,
    NOTIFY_DEEPLINK_URL_MAX_CHARS,
    NOTIFY_TEMPLATE_ACTION_CARD,
    NOTIFY_TEMPLATE_MARKDOWN,
    NOTIFY_TEMPLATE_TEXT,
    NOTIFY_TITLE_MAX_CHARS,
    TEMPLATE_INVALID_MESSAGE,
    TITLE_REQUIRED_MESSAGE,
    TITLE_TOO_LONG_MESSAGE,
    NotifyAcceptError,
)
from easyauth.notify.models import NOTIFY_TEMPLATE_VALUES


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


@dataclass(frozen=True, slots=True)
class NotifyMessageInput:
    """通知正文输入: 受理校验、幂等哈希与落库共用同一字段集。"""

    template: str
    content: str
    title: str = ""
    deeplink_url: str = ""
    deeplink_title: str = DEFAULT_DEEPLINK_TITLE
    dedup_key: str = ""
    biz_tag: str = ""
    recipients: tuple[str, ...] = ()


def compute_payload_hash(message: NotifyMessageInput) -> str:
    """按契约 §N2 对规范化字段全集做幂等哈希。"""
    canonical = json.dumps(
        {
            "template": message.template,
            "title": message.title,
            "content": message.content,
            "deeplink_url": message.deeplink_url,
            "deeplink_title": message.deeplink_title,
            "biz_tag": message.biz_tag,
            "recipients": sorted(message.recipients),
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class NormalizedInput:
    template: str
    title: str
    content: str
    deeplink_url: str
    deeplink_title: str
    dedup_key: str
    biz_tag: str


def normalize_and_validate(message: NotifyMessageInput) -> NormalizedInput:
    _validate_common_fields(message)
    effective_title, effective_deeplink, effective_deeplink_title = _template_fields(message)
    return NormalizedInput(
        template=message.template,
        title=effective_title,
        content=message.content,
        deeplink_url=effective_deeplink,
        deeplink_title=effective_deeplink_title,
        dedup_key=message.dedup_key,
        biz_tag=message.biz_tag,
    )


def _validate_common_fields(message: NotifyMessageInput) -> None:
    if message.template not in NOTIFY_TEMPLATE_VALUES:
        raise NotifyAcceptError(
            kind="validation_error",
            message=TEMPLATE_INVALID_MESSAGE,
            field="template",
        )
    if not message.content:
        raise NotifyAcceptError(
            kind="validation_error",
            message=CONTENT_REQUIRED_MESSAGE,
            field="content",
        )
    if len(message.title) > NOTIFY_TITLE_MAX_CHARS:
        raise NotifyAcceptError(
            kind="validation_error",
            message=TITLE_TOO_LONG_MESSAGE,
            field="title",
        )
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
    if len(message.deeplink_title) > NOTIFY_DEEPLINK_TITLE_MAX_CHARS:
        raise NotifyAcceptError(
            kind="validation_error",
            message=DEEPLINK_TITLE_TOO_LONG_MESSAGE,
            field="deeplink_title",
        )


def _template_fields(message: NotifyMessageInput) -> tuple[str, str, str]:
    if message.template == NOTIFY_TEMPLATE_TEXT:
        # text 模板忽略 title / deeplink。
        return "", "", DEFAULT_DEEPLINK_TITLE
    if message.template == NOTIFY_TEMPLATE_MARKDOWN:
        if not message.title:
            raise NotifyAcceptError(
                kind="validation_error",
                message=TITLE_REQUIRED_MESSAGE,
                field="title",
            )
        return message.title, "", DEFAULT_DEEPLINK_TITLE
    # action_card
    if not message.title:
        raise NotifyAcceptError(
            kind="validation_error",
            message=TITLE_REQUIRED_MESSAGE,
            field="title",
        )
    if not message.deeplink_url:
        raise NotifyAcceptError(
            kind="validation_error",
            message=DEEPLINK_REQUIRED_MESSAGE,
            field="deeplink_url",
        )
    if not _is_valid_deeplink_url(message.deeplink_url):
        raise NotifyAcceptError(
            kind="validation_error",
            message=DEEPLINK_URL_INVALID_MESSAGE,
            field="deeplink_url",
        )
    return message.title, message.deeplink_url, message.deeplink_title or DEFAULT_DEEPLINK_TITLE


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
