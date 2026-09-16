from __future__ import annotations

from urllib.parse import quote

import pytest

from easyauth.applications.models import App
from easyauth.notify.contracts import NOTIFY_MSG_MAX_BYTES, NotifyAcceptError
from easyauth.notify.messages import (
    DingTalkMsgSource,
    NotifyMessageInput,
    build_dingtalk_msg,
    dingtalk_msg_utf8_size,
    normalize_and_validate,
)
from easyauth.notify.oa import OA_MSGTYPE

pytestmark = pytest.mark.django_db


def _app() -> App:
    return App.objects.create(app_key="msg-build-app", name="消息组装")


def test_build_always_oa() -> None:
    msg = build_dingtalk_msg(
        app=_app(),
        source=DingTalkMsgSource(title="问候", content="你好"),
    )
    assert msg["msgtype"] == OA_MSGTYPE
    oa = msg["oa"]
    assert isinstance(oa, dict)
    body = oa["body"]
    assert isinstance(body, dict)
    assert body["content"] == "你好"
    assert body["title"] == "消息组装 · 问候"


def test_msg_utf8_size_counts_multibyte() -> None:
    msg = build_dingtalk_msg(
        app=_app(),
        source=DingTalkMsgSource(title="标题", content="中" * 10),
    )
    size = dingtalk_msg_utf8_size(msg)
    min_multibyte_size = 30
    assert size > min_multibyte_size


def test_msg_size_boundary_exactly_2048_ok_above_raises() -> None:
    app = _app()

    def size_for(n: int) -> int:
        return dingtalk_msg_utf8_size(
            build_dingtalk_msg(
                app=app,
                source=DingTalkMsgSource(title="t", content="x" * n),
            ),
        )

    lo, hi = 0, 3000
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if size_for(mid) <= NOTIFY_MSG_MAX_BYTES:
            lo = mid
        else:
            hi = mid - 1
    assert size_for(lo) <= NOTIFY_MSG_MAX_BYTES
    assert size_for(lo + 1) > NOTIFY_MSG_MAX_BYTES


def test_normalize_requires_title() -> None:
    with pytest.raises(NotifyAcceptError) as exc:
        _ = normalize_and_validate(
            NotifyMessageInput(
                title="",
                content="c",
            ),
        )
    assert exc.value.field == "title"


def test_normalize_deeplink_https_and_dingtalk_protocol() -> None:
    ok_https = normalize_and_validate(
        NotifyMessageInput(
            title="t",
            content="c",
            deeplink_url="https://example.com/path",
        ),
    )
    assert ok_https.deeplink_url == "https://example.com/path"

    embedded = quote("https://example.com/inner", safe="")
    dingtalk_url = f"dingtalk://dingtalkclient/page/link?url={embedded}&pc_slide=true"
    ok_dt = normalize_and_validate(
        NotifyMessageInput(
            title="t",
            content="c",
            deeplink_url=dingtalk_url,
        ),
    )
    assert ok_dt.deeplink_url == dingtalk_url

    with pytest.raises(NotifyAcceptError) as exc:
        _ = normalize_and_validate(
            NotifyMessageInput(
                title="t",
                content="c",
                deeplink_url="http://insecure.example.com",
            ),
        )
    assert exc.value.field == "deeplink_url"

    bad_embedded = quote("http://insecure.example.com", safe="")
    with pytest.raises(NotifyAcceptError):
        _ = normalize_and_validate(
            NotifyMessageInput(
                title="t",
                content="c",
                deeplink_url=f"dingtalk://dingtalkclient/page/link?url={bad_embedded}",
            ),
        )


@pytest.mark.parametrize(
    "deeplink_url",
    [
        "https://?",
        "https:///x",
        "https://",
        "https://[",
        "https://example.com:bad/path",
        "https://example.com:99999/path",
        "https://exa mple.com/path",
    ],
)
def test_normalize_rejects_malformed_https_deeplink(deeplink_url: str) -> None:
    with pytest.raises(NotifyAcceptError) as exc:
        _ = normalize_and_validate(
            NotifyMessageInput(
                title="t",
                content="c",
                deeplink_url=deeplink_url,
            ),
        )
    assert exc.value.field == "deeplink_url"


def test_normalize_accepts_https_deeplink_with_explicit_port() -> None:
    result = normalize_and_validate(
        NotifyMessageInput(
            title="t",
            content="c",
            deeplink_url="https://example.com:8443/path",
        ),
    )
    assert result.deeplink_url == "https://example.com:8443/path"


def test_normalize_rejects_malformed_https_embedded_in_dingtalk() -> None:
    embedded = quote("https://?", safe="")
    with pytest.raises(NotifyAcceptError) as exc:
        _ = normalize_and_validate(
            NotifyMessageInput(
                title="t",
                content="c",
                deeplink_url=f"dingtalk://dingtalkclient/page/link?url={embedded}",
            ),
        )
    assert exc.value.field == "deeplink_url"


def test_normalize_keeps_optional_deeplink_empty() -> None:
    result = normalize_and_validate(
        NotifyMessageInput(
            title="标题",
            content="body",
            deeplink_url="",
        ),
    )
    assert result.title == "标题"
    assert result.deeplink_url == ""
