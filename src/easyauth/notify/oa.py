"""钉钉工作通知 OA 载荷: 纯文本正文、时间表单与可选跳转。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from django.utils import timezone

from easyauth.notify.contracts import (
    OA_BODY_TITLE_MAX_CHARS,
    OA_BODY_TITLE_SEPARATOR,
    SHANGHAI_TZ,
)

if TYPE_CHECKING:
    from datetime import datetime

OA_MSGTYPE: Final = "oa"
OA_FORM_TIME_KEY: Final = "时间"
OA_FORM_TIME_FORMAT: Final = "%Y-%m-%d %H:%M:%S"
_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_FENCE = re.compile(r"```[\w+-]*\n?(.*?)```", re.DOTALL)
_IMAGE_OR_LINK = re.compile(r"!\[([^\]]*)\]\([^)]+\)|\[([^\]]+)\]\([^)]+\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
# 只剥 *斜体*, 不用 _..._ : 会把「文件_名称_备份」中的中文片段吃掉。
_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_LIST_MARKER = re.compile(r"^(\s*)(?:[-*+]|\d+\.)\s+", re.MULTILINE)
_EXTRA_NEWLINES = re.compile(r"\n{3,}")


@dataclass(frozen=True, slots=True)
class OaBuildInput:
    title: str
    content: str
    head_text: str
    head_bgcolor: str
    deeplink_url: str = ""
    fields: tuple[tuple[str, str], ...] = ()
    author: str = ""
    sent_at: datetime | None = None


def markdown_to_plain_text(text: str) -> str:
    """去掉 markdown 标记, 保留换行; 供 OA body.content 使用。"""
    stripped = text.replace("\r\n", "\n").replace("\r", "\n")
    stripped = _FENCE.sub(_fence_body, stripped)
    stripped = _HEADING.sub("", stripped)
    stripped = _IMAGE_OR_LINK.sub(_link_label, stripped)
    stripped = _BOLD.sub(_first_group, stripped)
    stripped = _ITALIC.sub(_first_group, stripped)
    stripped = _INLINE_CODE.sub(r"\1", stripped)
    stripped = _LIST_MARKER.sub(r"\1", stripped)
    stripped = _EXTRA_NEWLINES.sub("\n\n", stripped)
    return stripped.strip("\n")


def shanghai_clock(sent_at: datetime) -> str:
    if sent_at.tzinfo is None:
        message = "通知发送时间必须带时区。"
        raise ValueError(message)
    return sent_at.astimezone(SHANGHAI_TZ).strftime(OA_FORM_TIME_FORMAT)


def compose_oa_body_title(*, app_name: str, title: str) -> str:
    """body.title = 「应用中文名 · 通知标题」。只截标题, 永不截应用名。

    钉钉建议 50 字以内; 这里把合成标题压到 OA_BODY_TITLE_MAX_CHARS(40)。
    应用名本身超过上限时保留全名, 宁可超长也不截断身份。
    """
    prefix = app_name.strip()
    if not prefix:
        message = "应用名称不能为空。"
        raise ValueError(message)
    clipped_title = title.strip()
    remaining = OA_BODY_TITLE_MAX_CHARS - len(prefix) - len(OA_BODY_TITLE_SEPARATOR)
    if remaining <= 0 or not clipped_title:
        return prefix
    return f"{prefix}{OA_BODY_TITLE_SEPARATOR}{clipped_title[:remaining]}"


def build_oa_msg(parts: OaBuildInput) -> dict[str, object]:
    sent_at = parts.sent_at if parts.sent_at is not None else timezone.now()
    body: dict[str, object] = {
        "title": parts.title,
        "form": _oa_form(parts.fields, sent_at),
        "content": markdown_to_plain_text(parts.content),
    }
    if parts.author:
        body["author"] = parts.author
    oa: dict[str, object] = {
        "head": {"bgcolor": parts.head_bgcolor, "text": parts.head_text},
        "body": body,
    }
    if parts.deeplink_url:
        oa["message_url"] = parts.deeplink_url
    return {"msgtype": OA_MSGTYPE, "oa": oa}


def _oa_form(
    fields: tuple[tuple[str, str], ...],
    sent_at: datetime,
) -> list[dict[str, str]]:
    rows = [{"key": OA_FORM_TIME_KEY, "value": shanghai_clock(sent_at)}]
    rows.extend({"key": key, "value": value} for key, value in fields)
    return rows


def _fence_body(match: re.Match[str]) -> str:
    return match.group(1).rstrip("\n")


def _link_label(match: re.Match[str]) -> str:
    return match.group(1) or match.group(2) or ""


def _first_group(match: re.Match[str]) -> str:
    return match.group(1) or match.group(2) or ""
