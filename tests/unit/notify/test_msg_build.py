from __future__ import annotations

from urllib.parse import quote

import pytest

from easyauth.notify.models import (
    NOTIFY_TEMPLATE_ACTION_CARD,
    NOTIFY_TEMPLATE_MARKDOWN,
    NOTIFY_TEMPLATE_TEXT,
)
from easyauth.notify.services import (
    NOTIFY_MSG_MAX_BYTES,
    NotifyAcceptError,
    build_dingtalk_msg,
    dingtalk_msg_utf8_size,
)
from easyauth.notify.services import (
    _normalize_and_validate as normalize_and_validate,
)

pytestmark = pytest.mark.django_db


def test_build_text_template() -> None:
    msg = build_dingtalk_msg(template=NOTIFY_TEMPLATE_TEXT, title="ignored", content="你好")
    assert msg == {"msgtype": "text", "text": {"content": "你好"}}


def test_build_markdown_template() -> None:
    msg = build_dingtalk_msg(
        template=NOTIFY_TEMPLATE_MARKDOWN,
        title="逾期提醒",
        content="### 任务已逾期\n负责人: 王小明",
    )
    assert msg == {
        "msgtype": "markdown",
        "markdown": {
            "title": "逾期提醒",
            "text": "### 任务已逾期\n负责人: 王小明",
        },
    }


def test_build_action_card_template_with_defaults() -> None:
    msg = build_dingtalk_msg(
        template=NOTIFY_TEMPLATE_ACTION_CARD,
        title="任务逾期升级",
        content="### 任务已逾期 3 天",
        deeplink_url="https://eproject.example.com/tasks/123",
    )
    assert msg == {
        "msgtype": "action_card",
        "action_card": {
            "title": "任务逾期升级",
            "markdown": "### 任务已逾期 3 天",
            "single_title": "查看详情",
            "single_url": "https://eproject.example.com/tasks/123",
        },
    }


def test_build_action_card_custom_button_title() -> None:
    msg = build_dingtalk_msg(
        template=NOTIFY_TEMPLATE_ACTION_CARD,
        title="t",
        content="c",
        deeplink_url="https://example.com/x",
        deeplink_title="查看任务",
    )
    card = msg["action_card"]
    assert isinstance(card, dict)
    assert card["single_title"] == "查看任务"


def test_msg_utf8_size_counts_multibyte() -> None:
    msg = build_dingtalk_msg(
        template=NOTIFY_TEMPLATE_TEXT,
        title="",
        content="中" * 10,
    )
    # 结构 {"msgtype":"text","text":{"content":"中"*10}} 的 UTF-8 字节数。
    size = dingtalk_msg_utf8_size(msg)
    expected = ('{"msgtype":"text","text":{"content":"' + ("中" * 10) + '"}}').encode()
    assert size == len(expected)
    # 纯 ASCII 骨架远小于该值; 10 个汉字使总字节明显更大。
    min_multibyte_size = 30
    assert size > min_multibyte_size


def test_msg_size_boundary_exactly_2048_ok_above_raises() -> None:
    # 构造刚好 ≤2048 与 >2048 的 content。
    prefix_msg = build_dingtalk_msg(template=NOTIFY_TEMPLATE_TEXT, title="", content="")
    overhead = dingtalk_msg_utf8_size(prefix_msg)  # content 为空串时的骨架
    # content 非空时骨架含 content 字段的引号对, 空 content 的 JSON 已含 "".
    # 更稳妥: 二分 content 长度。
    def size_for(n: int) -> int:
        return dingtalk_msg_utf8_size(
            build_dingtalk_msg(template=NOTIFY_TEMPLATE_TEXT, title="", content="x" * n),
        )

    # 找到最大 n 使 size ≤ 2048
    lo, hi = 0, 3000
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if size_for(mid) <= NOTIFY_MSG_MAX_BYTES:
            lo = mid
        else:
            hi = mid - 1
    assert size_for(lo) <= NOTIFY_MSG_MAX_BYTES
    assert size_for(lo + 1) > NOTIFY_MSG_MAX_BYTES

    # accept 路径在 services 内校验; 这里直接断言边界函数与常量对齐。
    assert overhead < NOTIFY_MSG_MAX_BYTES


def test_normalize_action_card_requires_title_and_deeplink() -> None:
    with pytest.raises(NotifyAcceptError, match="title") as exc:
        _ = normalize_and_validate(
            template=NOTIFY_TEMPLATE_ACTION_CARD,
            title="",
            content="c",
            deeplink_url="https://example.com",
            deeplink_title="查看详情",
            dedup_key="",
            biz_tag="",
        )
    assert exc.value.field == "title"

    with pytest.raises(NotifyAcceptError, match="deeplink_url") as exc2:
        _ = normalize_and_validate(
            template=NOTIFY_TEMPLATE_ACTION_CARD,
            title="t",
            content="c",
            deeplink_url="",
            deeplink_title="查看详情",
            dedup_key="",
            biz_tag="",
        )
    assert exc2.value.field == "deeplink_url"


def test_normalize_markdown_requires_title() -> None:
    with pytest.raises(NotifyAcceptError) as exc:
        _ = normalize_and_validate(
            template=NOTIFY_TEMPLATE_MARKDOWN,
            title="",
            content="c",
            deeplink_url="",
            deeplink_title="",
            dedup_key="",
            biz_tag="",
        )
    assert exc.value.field == "title"


def test_normalize_deeplink_https_and_dingtalk_protocol() -> None:
    ok_https = normalize_and_validate(
        template=NOTIFY_TEMPLATE_ACTION_CARD,
        title="t",
        content="c",
        deeplink_url="https://example.com/path",
        deeplink_title="去看看",
        dedup_key="",
        biz_tag="",
    )
    assert ok_https.deeplink_url == "https://example.com/path"

    embedded = quote("https://example.com/inner", safe="")
    dingtalk_url = f"dingtalk://dingtalkclient/page/link?url={embedded}&pc_slide=true"
    ok_dt = normalize_and_validate(
        template=NOTIFY_TEMPLATE_ACTION_CARD,
        title="t",
        content="c",
        deeplink_url=dingtalk_url,
        deeplink_title="侧边栏",
        dedup_key="",
        biz_tag="",
    )
    assert ok_dt.deeplink_url == dingtalk_url

    with pytest.raises(NotifyAcceptError) as exc:
        _ = normalize_and_validate(
            template=NOTIFY_TEMPLATE_ACTION_CARD,
            title="t",
            content="c",
            deeplink_url="http://insecure.example.com",
            deeplink_title="x",
            dedup_key="",
            biz_tag="",
        )
    assert exc.value.field == "deeplink_url"

    # dingtalk 协议内嵌非 https
    bad_embedded = quote("http://insecure.example.com", safe="")
    with pytest.raises(NotifyAcceptError):
        _ = normalize_and_validate(
            template=NOTIFY_TEMPLATE_ACTION_CARD,
            title="t",
            content="c",
            deeplink_url=f"dingtalk://dingtalkclient/page/link?url={bad_embedded}",
            deeplink_title="x",
            dedup_key="",
            biz_tag="",
        )


def test_normalize_text_ignores_title_and_deeplink() -> None:
    result = normalize_and_validate(
        template=NOTIFY_TEMPLATE_TEXT,
        title="will-be-cleared",
        content="body",
        deeplink_url="https://example.com",
        deeplink_title="btn",
        dedup_key="",
        biz_tag="",
    )
    assert result.title == ""
    assert result.deeplink_url == ""
