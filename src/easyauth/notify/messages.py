from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING
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

if TYPE_CHECKING:
    from collections.abc import Sequence


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
    biz_tag: str,
    recipients: Sequence[str],
) -> str:
    canonical = json.dumps(
        {
            "template": template,
            "title": title,
            "content": content,
            "deeplink_url": deeplink_url,
            "deeplink_title": deeplink_title,
            "biz_tag": biz_tag,
            "recipients": sorted(recipients),
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


def normalize_and_validate(  # noqa: PLR0913 - 受理字段全集。
    *,
    template: str,
    title: str,
    content: str,
    deeplink_url: str,
    deeplink_title: str,
    dedup_key: str,
    biz_tag: str,
) -> NormalizedInput:
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
    return NormalizedInput(
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
