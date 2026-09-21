from __future__ import annotations

import json
from typing import TYPE_CHECKING, Self
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

import pytest

from easyauth.integrations.dingtalk import api_client as client_module
from easyauth.integrations.dingtalk.api_client import (
    DINGTALK_OAPI_BASE_URL,
    WORK_NOTIFICATION_MAX_USERIDS,
    DingTalkApiClient,
    DingTalkApiRequestError,
    DingTalkApiUnavailableError,
)
from easyauth.integrations.dingtalk.work_notification import parse_send_result

if TYPE_CHECKING:
    from types import TracebackType
    from urllib.request import Request

TEST_APP_SECRET = "app-secret"
TEST_AGENT_ID = 12345
TEST_OAPI_ERRCODE = 88
PROGRESS_STATUS_DONE = 2
EXPECTED_PROGRESS_AND_RESULT_CALLS = 2
EXPECTED_TOKEN_PLUS_TWO_SENDS = 3
CACHED_TOKEN = "cached-token"


class _Response:
    body: bytes

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self.body[:amount]


class _Cache:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def get(self, key: str) -> object | None:
        return self.values.get(key)

    def set(self, key: str, value: object, timeout: int | None = None) -> None:
        del timeout
        self.values[key] = value

    def delete(self, key: str) -> None:
        _ = self.values.pop(key, None)


def _client() -> DingTalkApiClient:
    return DingTalkApiClient(
        app_key="app-key",
        app_secret=TEST_APP_SECRET,
        timeout_seconds=5,
    )


def _patch_urlopen(
    monkeypatch: pytest.MonkeyPatch,
    *,
    responses: list[_Response] | None = None,
    capture: list[Request] | None = None,
) -> list[Request]:
    requests: list[Request] = capture if capture is not None else []
    response_iter = iter(responses or [])

    def fake_urlopen(request: Request, *, timeout: float) -> _Response:
        del timeout
        requests.append(request)
        return next(response_iter)

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    return requests


def _seed_token_cache(
    monkeypatch: pytest.MonkeyPatch,
    token: str = CACHED_TOKEN,
) -> None:
    fake_cache = _Cache()
    fake_cache.values[
        client_module._access_token_cache_key("app-key", TEST_APP_SECRET)  # noqa: SLF001
    ] = token
    monkeypatch.setattr(client_module, "cache", fake_cache)


def test_send_work_notification_uses_oapi_and_query_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_token_cache(monkeypatch)
    captured: list[Request] = []
    _patch_urlopen(
        monkeypatch,
        responses=[_Response(b'{"errcode":0,"errmsg":"ok","task_id":9876543210}')],
        capture=captured,
    )
    msg = {"msgtype": "text", "text": {"content": "hi"}}

    task_id = _client().send_work_notification(
        agent_id=TEST_AGENT_ID,
        userid_list=["user1", "user2"],
        msg=msg,
    )

    assert task_id == "9876543210"
    assert len(captured) == 1
    request = captured[0]
    parsed = urlparse(request.full_url)
    assert f"{parsed.scheme}://{parsed.netloc}" == DINGTALK_OAPI_BASE_URL
    assert parsed.path == "/topapi/message/corpconversation/asyncsend_v2"
    query = parse_qs(parsed.query)
    assert query["access_token"] == [CACHED_TOKEN]
    assert request.get_header("X-acs-dingtalk-access-token") is None
    body = json.loads(request.data.decode("utf-8"))  # type: ignore[union-attr]
    assert body["agent_id"] == TEST_AGENT_ID
    assert body["userid_list"] == "user1,user2"
    assert body["msg"] == msg


def test_send_work_notification_rejects_empty_and_over_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_token_cache(monkeypatch)
    client = _client()
    msg = {"msgtype": "text", "text": {"content": "x"}}

    with pytest.raises(DingTalkApiRequestError, match="不能为空"):
        _ = client.send_work_notification(agent_id=1, userid_list=[], msg=msg)

    with pytest.raises(DingTalkApiRequestError, match=str(WORK_NOTIFICATION_MAX_USERIDS)):
        _ = client.send_work_notification(
            agent_id=1,
            userid_list=[f"u{i}" for i in range(WORK_NOTIFICATION_MAX_USERIDS + 1)],
            msg=msg,
        )


def test_send_work_notification_oapi_business_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_token_cache(monkeypatch)
    _patch_urlopen(
        monkeypatch,
        responses=[
            _Response(b'{"errcode":88,"errmsg":"permission denied"}'),
        ],
    )

    with pytest.raises(DingTalkApiRequestError, match="permission denied") as exc:
        _ = _client().send_work_notification(
            agent_id=1,
            userid_list=["u1"],
            msg={"msgtype": "text", "text": {"content": "x"}},
        )
    assert exc.value.errcode == TEST_OAPI_ERRCODE
    assert exc.value.status_code is None


def test_get_send_progress_and_result(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_token_cache(monkeypatch)
    captured: list[Request] = []
    _patch_urlopen(
        monkeypatch,
        responses=[
            _Response(
                b'{"errcode":0,"progress":{"status":2,"progress_in_percent":100}}',
            ),
            _Response(
                b'{"errcode":0,"send_result":{"read_user_id_list":["u1"],'
                b'"unread_user_id_list":[],"invalid_user_id_list":[],'
                b'"failed_user_id_list":[],"forbidden_user_id_list":[],'
                b'"forbidden_list":[]}}',
            ),
        ],
        capture=captured,
    )
    client = _client()

    progress = client.get_send_progress(agent_id=9, task_id="42")
    result = client.get_send_result(agent_id=9, task_id="42")

    assert progress.status == PROGRESS_STATUS_DONE
    assert result.read_user_ids == frozenset({"u1"})
    assert len(captured) == EXPECTED_PROGRESS_AND_RESULT_CALLS
    assert captured[0].full_url.startswith(
        f"{DINGTALK_OAPI_BASE_URL}/topapi/message/corpconversation/getsendprogress",
    )
    assert captured[1].full_url.startswith(
        f"{DINGTALK_OAPI_BASE_URL}/topapi/message/corpconversation/getsendresult",
    )


def test_get_send_result_accepts_omitted_receipt_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_token_cache(monkeypatch)
    _patch_urlopen(
        monkeypatch,
        responses=[
            _Response(
                b'{"errcode":0,"send_result":{"failed_user_id_list":[],'
                b'"forbidden_list":[],"invalid_dept_id_list":["9"],'
                b'"invalid_user_id_list":[],"read_user_id_list":[],'
                b'"unread_user_id_list":["u1"]}}',
            ),
        ],
    )

    result = _client().get_send_result(agent_id=9, task_id="42")
    assert result.unread_user_ids == frozenset({"u1"})
    assert result.forbidden_user_ids == frozenset()
    assert result.forbidden_receipts == ()


def test_parse_send_result_omitted_or_null_lists_are_empty() -> None:
    omitted = parse_send_result({})
    assert omitted.invalid_user_ids == frozenset()
    assert omitted.failed_user_ids == frozenset()
    assert omitted.forbidden_user_ids == frozenset()
    assert omitted.read_user_ids == frozenset()
    assert omitted.unread_user_ids == frozenset()
    assert omitted.forbidden_receipts == ()

    null_payload: dict[str, object] = {
        "failed_user_id_list": None,
        "forbidden_list": None,
        "forbidden_user_id_list": None,
        "invalid_user_id_list": None,
        "read_user_id_list": None,
        "unread_user_id_list": None,
    }
    nulls = parse_send_result(null_payload)
    assert nulls.forbidden_user_ids == frozenset()
    assert nulls.forbidden_receipts == ()
    assert nulls.read_user_ids == frozenset()


def test_parse_send_result_production_shape_round_trips() -> None:
    payload: dict[str, object] = {
        "failed_user_id_list": [],
        "forbidden_list": [],
        "invalid_dept_id_list": ["dept-1"],
        "invalid_user_id_list": [],
        "read_user_id_list": [],
        "unread_user_id_list": ["u1"],
    }
    result = parse_send_result(payload)
    assert result.unread_user_ids == frozenset({"u1"})
    assert result.forbidden_user_ids == frozenset()
    assert result.invalid_user_ids == frozenset()
    assert result.failed_user_ids == frozenset()
    assert result.read_user_ids == frozenset()
    assert result.forbidden_receipts == ()


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"invalid_user_id_list": "u1"}, "invalid_user_id_list"),
        ({"failed_user_id_list": 1}, "failed_user_id_list"),
        ({"read_user_id_list": {"u1": 1}}, "read_user_id_list"),
        ({"forbidden_list": "x"}, "forbidden_list"),
        ({"unread_user_id_list": [""]}, "无效 userid"),
        ({"forbidden_user_id_list": [1]}, "无效 userid"),
    ],
)
def test_parse_send_result_rejects_non_list_and_bad_items(
    payload: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(DingTalkApiRequestError, match=match):
        _ = parse_send_result(payload)


def test_oapi_network_error_maps_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_token_cache(monkeypatch)
    network_down = "down"

    def boom(_request: Request, *, timeout: float) -> _Response:
        del timeout
        raise URLError(network_down)

    monkeypatch.setattr(client_module, "urlopen", boom)

    with pytest.raises(DingTalkApiUnavailableError):
        _ = _client().send_work_notification(
            agent_id=1,
            userid_list=["u1"],
            msg={"msgtype": "text", "text": {"content": "x"}},
        )


def test_send_reuses_access_token_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cache = _Cache()
    monkeypatch.setattr(client_module, "cache", fake_cache)
    captured: list[Request] = []
    _patch_urlopen(
        monkeypatch,
        responses=[
            _Response(b'{"accessToken":"tok-1","expireIn":7200}'),
            _Response(b'{"errcode":0,"errmsg":"ok","task_id":1}'),
            _Response(b'{"errcode":0,"errmsg":"ok","task_id":2}'),
        ],
        capture=captured,
    )
    client = _client()
    msg = {"msgtype": "text", "text": {"content": "x"}}

    assert client.send_work_notification(agent_id=1, userid_list=["a"], msg=msg) == "1"
    assert client.send_work_notification(agent_id=1, userid_list=["b"], msg=msg) == "2"

    # 第 1 次为 accessToken; 后两次为 oapi, 共 3 次 HTTP。
    assert len(captured) == EXPECTED_TOKEN_PLUS_TWO_SENDS
    assert "/v1.0/oauth2/accessToken" in captured[0].full_url
    assert "access_token=tok-1" in captured[1].full_url
    assert "access_token=tok-1" in captured[2].full_url
