from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from easyauth.applications.models import App
from easyauth.applications.notify_appearance import (
    EASYAUTH_NOTIFY_HEAD_BGCOLOR,
    NOTIFY_HEAD_BGCOLOR_PALETTE,
    normalize_notify_head_bgcolor,
    palette_notify_head_bgcolor,
)
from easyauth.notify.head import resolve_notify_head
from easyauth.notify.messages import DingTalkMsgSource, build_dingtalk_msg
from easyauth.notify.oa import OA_FORM_TIME_KEY, OA_MSGTYPE, markdown_to_plain_text

pytestmark = pytest.mark.django_db

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _oa_body(msg: dict[str, object]) -> dict[str, object]:
    oa = msg["oa"]
    assert isinstance(oa, dict)
    body = oa["body"]
    assert isinstance(body, dict)
    return body


def test_build_oa_payload_head_body_form_and_time() -> None:
    app = App.objects.create(app_key="easylearning", name="学习工作台")
    sent_at = datetime(2026, 9, 16, 10, 5, tzinfo=SHANGHAI)
    msg = build_dingtalk_msg(
        app=app,
        source=DingTalkMsgSource(
            title="课程提醒",
            content="### 请完成本周学习\n**必修课**",
            deeplink_url="https://learn.example.com/lessons/1",
            fields=(("来自", "张三"),),
            author="张三",
        ),
        sent_at=sent_at,
    )
    assert msg["msgtype"] == OA_MSGTYPE
    oa = msg["oa"]
    assert isinstance(oa, dict)
    assert oa["message_url"] == "https://learn.example.com/lessons/1"
    head = oa["head"]
    assert isinstance(head, dict)
    assert head["text"] == "学习工作台"
    assert head["bgcolor"] == palette_notify_head_bgcolor(app.id)
    body = _oa_body(msg)
    assert body["title"] == "课程提醒"
    assert body["content"] == "请完成本周学习\n必修课"
    assert body["author"] == "张三"
    assert body["form"] == [
        {"key": OA_FORM_TIME_KEY, "value": "10:05"},
        {"key": "来自", "value": "张三"},
    ]


def test_easyauth_identity_uses_site_title_and_fixed_blue() -> None:
    app = App.objects.create(
        app_key="easyauth-lifecycle",
        name="生命周期通知",
        notify_head_bgcolor="FFC62828",
    )
    text, color = resolve_notify_head(app=app)
    assert text == "统一身份认证"
    assert color == EASYAUTH_NOTIFY_HEAD_BGCOLOR


def test_app_display_name_override_never_uses_slug() -> None:
    app = App.objects.create(app_key="easylearning", name="EasyLearning")
    msg = build_dingtalk_msg(
        app=app,
        source=DingTalkMsgSource(
            title="提醒",
            content="正文",
            app_display_name="学习工作台",
        ),
        sent_at=datetime(2026, 9, 16, 9, 0, tzinfo=SHANGHAI),
    )
    oa = msg["oa"]
    assert isinstance(oa, dict)
    head = oa["head"]
    assert isinstance(head, dict)
    assert head["text"] == "学习工作台"
    assert app.app_key not in str(msg)


def test_custom_color_normalizes_and_palette_is_stable() -> None:
    assert normalize_notify_head_bgcolor("#1a7f4c") == "FF1A7F4C"
    first = palette_notify_head_bgcolor(7)
    second = palette_notify_head_bgcolor(7)
    assert first == second
    assert first in NOTIFY_HEAD_BGCOLOR_PALETTE
    app = App.objects.create(
        app_key="colored-app",
        name="色带应用",
        notify_head_bgcolor="#c62828",
    )
    _, color = resolve_notify_head(app=app)
    assert color == "FFC62828"


def test_markdown_stripped_to_plain_text_keeps_line_breaks() -> None:
    plain = markdown_to_plain_text("### 标题\n**加粗** 与 `代码`\n- 列表")
    assert "###" not in plain
    assert "**" not in plain
    assert "`" not in plain
    assert "\n" in plain
    assert "标题" in plain
    assert "加粗" in plain


def test_markdown_msgtype_path_is_gone() -> None:
    app = App.objects.create(app_key="oa-only", name="仅 OA")
    msg = build_dingtalk_msg(
        app=app,
        source=DingTalkMsgSource(title="标题", content="正文"),
        sent_at=datetime(2026, 9, 16, 8, 0, tzinfo=SHANGHAI),
    )
    assert msg["msgtype"] == "oa"
    assert "markdown" not in msg
    assert "text" not in msg
    assert "action_card" not in msg
