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
from easyauth.notify.contracts import (
    FIELDS_TIME_KEY_RESERVED_MESSAGE,
    FIELDS_TOO_MANY_MESSAGE,
    NOTIFY_FORM_FIELD_MAX_ITEMS,
    OA_BODY_TITLE_MAX_CHARS,
    OA_BODY_TITLE_SEPARATOR,
    NotifyAcceptError,
)
from easyauth.notify.head import resolve_notify_display_name, resolve_notify_head
from easyauth.notify.messages import (
    DingTalkMsgSource,
    NotifyMessageInput,
    build_dingtalk_msg,
    normalize_and_validate,
)
from easyauth.notify.oa import (
    OA_FORM_TIME_KEY,
    OA_MSGTYPE,
    compose_oa_body_title,
    markdown_to_plain_text,
)

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
    sent_at = datetime(2026, 9, 16, 10, 5, 7, tzinfo=SHANGHAI)
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
    assert body["title"] == "学习工作台 · 课程提醒"
    assert body["content"] == "请完成本周学习\n必修课"
    assert body["author"] == "张三"
    assert body["form"] == [
        {"key": OA_FORM_TIME_KEY, "value": "2026-09-16 10:05:07"},
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
    assert resolve_notify_display_name(app=app, app_display_name="应被忽略") == "统一身份认证"


def test_app_display_name_feeds_title_prefix_not_head() -> None:
    app = App.objects.create(app_key="easylearning", name="EasyLearning")
    msg = build_dingtalk_msg(
        app=app,
        source=DingTalkMsgSource(
            title="提醒",
            content="正文",
            app_display_name="学习工作台",
        ),
        sent_at=datetime(2026, 9, 16, 9, 0, 0, tzinfo=SHANGHAI),
    )
    oa = msg["oa"]
    assert isinstance(oa, dict)
    head = oa["head"]
    assert isinstance(head, dict)
    assert head["text"] == "EasyLearning"
    assert head["bgcolor"] == palette_notify_head_bgcolor(app.id)
    body = _oa_body(msg)
    assert body["title"] == "学习工作台 · 提醒"
    assert app.app_key not in str(msg)


def test_compose_oa_body_title_truncates_title_never_app_name() -> None:
    prefix = "学习工作台"
    long_title = "标" * 50
    composed = compose_oa_body_title(app_name=prefix, title=long_title)
    assert composed.startswith(f"{prefix}{OA_BODY_TITLE_SEPARATOR}")
    assert len(composed) == OA_BODY_TITLE_MAX_CHARS
    assert composed == f"{prefix}{OA_BODY_TITLE_SEPARATOR}{'标' * 32}"
    oversized = "甲" * (OA_BODY_TITLE_MAX_CHARS + 5)
    assert compose_oa_body_title(app_name=oversized, title="提醒") == oversized


def test_same_minute_form_values_differ_by_second() -> None:
    app = App.objects.create(app_key="clock-app", name="时钟应用")
    first = build_dingtalk_msg(
        app=app,
        source=DingTalkMsgSource(title="同一正文", content="相同内容"),
        sent_at=datetime(2026, 9, 16, 10, 5, 1, tzinfo=SHANGHAI),
    )
    second = build_dingtalk_msg(
        app=app,
        source=DingTalkMsgSource(title="同一正文", content="相同内容"),
        sent_at=datetime(2026, 9, 16, 10, 5, 2, tzinfo=SHANGHAI),
    )
    first_form = _oa_body(first)["form"]
    second_form = _oa_body(second)["form"]
    assert isinstance(first_form, list)
    assert isinstance(second_form, list)
    assert first_form[0]["value"] == "2026-09-16 10:05:01"
    assert second_form[0]["value"] == "2026-09-16 10:05:02"
    assert first_form[0]["value"] != second_form[0]["value"]


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
    assert plain == "标题\n加粗 与 代码\n列表"


def test_markdown_underscore_in_chinese_filename_is_kept() -> None:
    assert markdown_to_plain_text("文件_名称_备份") == "文件_名称_备份"
    assert markdown_to_plain_text("*斜体* 与 文件_名称_备份") == "斜体 与 文件_名称_备份"


def test_markdown_msgtype_path_is_gone() -> None:
    app = App.objects.create(app_key="oa-only", name="仅 OA")
    msg = build_dingtalk_msg(
        app=app,
        source=DingTalkMsgSource(title="标题", content="正文"),
        sent_at=datetime(2026, 9, 16, 8, 0, 0, tzinfo=SHANGHAI),
    )
    assert msg["msgtype"] == "oa"
    assert "markdown" not in msg
    assert "text" not in msg
    assert "action_card" not in msg


def test_normalize_rejects_more_than_five_caller_fields() -> None:
    too_many = tuple((f"k{index}", "v") for index in range(NOTIFY_FORM_FIELD_MAX_ITEMS + 1))
    with pytest.raises(NotifyAcceptError) as exc:
        _ = normalize_and_validate(
            NotifyMessageInput(title="t", content="c", fields=too_many),
        )
    assert exc.value.field == "fields"
    assert exc.value.message == FIELDS_TOO_MANY_MESSAGE


def test_normalize_rejects_reserved_time_form_key() -> None:
    with pytest.raises(NotifyAcceptError) as exc:
        _ = normalize_and_validate(
            NotifyMessageInput(
                title="t",
                content="c",
                fields=((OA_FORM_TIME_KEY, "应被拒绝"),),
            ),
        )
    assert exc.value.field == "fields"
    assert exc.value.message == FIELDS_TIME_KEY_RESERVED_MESSAGE
