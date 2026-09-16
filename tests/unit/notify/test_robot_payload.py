from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from easyauth.applications.models import App
from easyauth.notify.messages import DingTalkMsgSource
from easyauth.notify.oa import compose_oa_body_title
from easyauth.notify.robot import build_robot_markdown_text, build_robot_message_parts

pytestmark = pytest.mark.django_db

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_robot_markdown_matches_oa_identity_and_clock() -> None:
    sent_at = datetime(2026, 9, 16, 10, 5, 7, tzinfo=SHANGHAI)
    heading = compose_oa_body_title(app_name="学习工作台", title="课程提醒")
    text = build_robot_markdown_text(
        heading_title=heading,
        content="### 请完成本周学习\n**必修课**",
        author="张三",
        sender_fallback="学习工作台",
        sent_at=sent_at,
    )
    assert text == (
        "### 学习工作台 · 课程提醒\n### 请完成本周学习\n**必修课**\n\n10:05 · 来自 张三"
    )


def test_robot_message_parts_use_display_name_when_author_blank() -> None:
    app = App.objects.create(app_key="easylearning", name="EasyLearning")
    title, text = build_robot_message_parts(
        app=app,
        source=DingTalkMsgSource(
            title="提醒",
            content="正文",
            app_display_name="学习工作台",
        ),
        sent_at=datetime(2026, 9, 16, 9, 0, 0, tzinfo=SHANGHAI),
    )
    assert title == "学习工作台 · 提醒"
    assert text.startswith("### 学习工作台 · 提醒\n")
    assert text.endswith("09:00 · 来自 学习工作台")
