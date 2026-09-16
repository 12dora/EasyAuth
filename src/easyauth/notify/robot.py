"""服务号机器人一对一消息正文: 与 OA body 同一套应用名、标题、正文与发起方。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from easyauth.notify.contracts import SHANGHAI_TZ
from easyauth.notify.head import resolve_notify_display_name
from easyauth.notify.oa import compose_oa_body_title

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.applications.models import App
    from easyauth.notify.messages import DingTalkMsgSource

ROBOT_FOOTER_TIME_FORMAT: Final = "%H:%M"
ROBOT_SENDER_REQUIRED_MESSAGE: Final = "机器人消息发起方不能为空。"
ROBOT_SENT_AT_TZ_REQUIRED_MESSAGE: Final = "通知发送时间必须带时区。"


def shanghai_hm(sent_at: datetime) -> str:
    if sent_at.tzinfo is None:
        raise ValueError(ROBOT_SENT_AT_TZ_REQUIRED_MESSAGE)
    return sent_at.astimezone(SHANGHAI_TZ).strftime(ROBOT_FOOTER_TIME_FORMAT)


def build_robot_markdown_text(
    *,
    heading_title: str,
    content: str,
    author: str,
    sender_fallback: str,
    sent_at: datetime,
) -> str:
    """Markdown 正文: `### <应用名> · <标题>` + content + `HH:mm · 来自 <发起方>`。"""
    sender = author.strip() or sender_fallback.strip()
    if not sender:
        raise ValueError(ROBOT_SENDER_REQUIRED_MESSAGE)
    body = content.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    footer = f"{shanghai_hm(sent_at)} · 来自 {sender}"
    return f"### {heading_title}\n{body}\n\n{footer}"


def build_robot_message_parts(
    *,
    app: App,
    source: DingTalkMsgSource,
    sent_at: datetime,
) -> tuple[str, str]:
    """返回 (title, text), 供机器人 batchSend 的 msgParam 使用。"""
    display_name = resolve_notify_display_name(
        app=app,
        app_display_name=source.app_display_name,
    )
    heading_title = compose_oa_body_title(app_name=display_name, title=source.title)
    text = build_robot_markdown_text(
        heading_title=heading_title,
        content=source.content,
        author=source.author,
        sender_fallback=display_name,
        sent_at=sent_at,
    )
    return heading_title, text
