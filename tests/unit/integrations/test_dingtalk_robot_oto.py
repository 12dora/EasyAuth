from __future__ import annotations

import json
from typing import TYPE_CHECKING, Self

import pytest

from easyauth.integrations.dingtalk import api_client as client_module
from easyauth.integrations.dingtalk.api_client import (
    DINGTALK_API_BASE_URL,
    ROBOT_MSG_KEY_ACTION_CARD,
    ROBOT_MSG_KEY_MARKDOWN,
    ROBOT_OTO_BATCH_SEND_PATH,
    ROBOT_OTO_MAX_USERIDS,
    DingTalkApiClient,
    DingTalkApiRequestError,
    chunk_robot_user_ids,
)

if TYPE_CHECKING:
    from types import TracebackType
    from urllib.request import Request

TEST_APP_SECRET = "app-secret"
CACHED_TOKEN = "cached-token"
ROBOT_CODE = "svc-app-key"
EXPECTED_TOKEN_PLUS_TWO_BATCHES = 3


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
        app_key=ROBOT_CODE,
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


def _seed_token_cache(monkeypatch: pytest.MonkeyPatch, token: str = CACHED_TOKEN) -> None:
    fake_cache = _Cache()
    fake_cache.values[
        client_module._access_token_cache_key(ROBOT_CODE, TEST_APP_SECRET)  # noqa: SLF001
    ] = token
    monkeypatch.setattr(client_module, "cache", fake_cache)


def _ok_body(process_query_key: str = "pqk-1") -> bytes:
    return json.dumps(
        {
            "processQueryKey": process_query_key,
            "invalidStaffIdList": [],
            "flowControlledStaffIdList": [],
        },
    ).encode()


def test_robot_markdown_payload_uses_new_api_token_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_token_cache(monkeypatch)
    captured: list[Request] = []
    _patch_urlopen(monkeypatch, responses=[_Response(_ok_body())], capture=captured)

    results = _client().send_robot_oto_messages(
        robot_code=ROBOT_CODE,
        user_ids=["u1", "u2"],
        title="学习工作台 · 课程提醒",
        text="### 学习工作台 · 课程提醒\n请完成本周学习\n\n10:05 · 来自 张三",
    )

    assert len(results) == 1
    assert results[0].process_query_key == "pqk-1"
    assert results[0].user_ids == ("u1", "u2")
    assert len(captured) == 1
    request = captured[0]
    assert request.full_url == f"{DINGTALK_API_BASE_URL}{ROBOT_OTO_BATCH_SEND_PATH}"
    assert request.get_header("X-acs-dingtalk-access-token") == CACHED_TOKEN
    body = json.loads(request.data.decode("utf-8"))  # type: ignore[union-attr]
    assert body["robotCode"] == ROBOT_CODE
    assert body["userIds"] == ["u1", "u2"]
    assert body["msgKey"] == ROBOT_MSG_KEY_MARKDOWN
    param = json.loads(body["msgParam"])
    assert param == {
        "title": "学习工作台 · 课程提醒",
        "text": "### 学习工作台 · 课程提醒\n请完成本周学习\n\n10:05 · 来自 张三",
    }


def test_robot_action_card_payload_when_link_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_token_cache(monkeypatch)
    captured: list[Request] = []
    _patch_urlopen(monkeypatch, responses=[_Response(_ok_body("pqk-card"))], capture=captured)

    _ = _client().send_robot_oto_messages(
        robot_code=ROBOT_CODE,
        user_ids=["u1"],
        title="学习工作台 · 课程提醒",
        text="正文",
        single_url="https://learn.example.com/lessons/1",
    )

    body = json.loads(captured[0].data.decode("utf-8"))  # type: ignore[union-attr]
    assert body["msgKey"] == ROBOT_MSG_KEY_ACTION_CARD
    param = json.loads(body["msgParam"])
    assert param["singleTitle"] == "查看详情"
    assert param["singleURL"] == "https://learn.example.com/lessons/1"


def test_robot_batch_chunks_user_ids_and_reuses_access_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_cache = _Cache()
    monkeypatch.setattr(client_module, "cache", fake_cache)
    captured: list[Request] = []
    user_ids = [f"u{index}" for index in range(ROBOT_OTO_MAX_USERIDS + 1)]
    _patch_urlopen(
        monkeypatch,
        responses=[
            _Response(b'{"accessToken":"tok-robot","expireIn":7200}'),
            _Response(_ok_body("pqk-a")),
            _Response(_ok_body("pqk-b")),
        ],
        capture=captured,
    )

    results = _client().send_robot_oto_messages(
        robot_code=ROBOT_CODE,
        user_ids=user_ids,
        title="标题",
        text="正文",
    )

    assert chunk_robot_user_ids(user_ids) == (
        tuple(user_ids[:ROBOT_OTO_MAX_USERIDS]),
        (user_ids[ROBOT_OTO_MAX_USERIDS],),
    )
    assert [item.process_query_key for item in results] == ["pqk-a", "pqk-b"]
    assert results[0].user_ids == tuple(user_ids[:ROBOT_OTO_MAX_USERIDS])
    assert results[1].user_ids == (user_ids[ROBOT_OTO_MAX_USERIDS],)
    assert len(captured) == EXPECTED_TOKEN_PLUS_TWO_BATCHES
    assert "/v1.0/oauth2/accessToken" in captured[0].full_url
    token_body = json.loads(captured[0].data.decode("utf-8"))  # type: ignore[union-attr]
    assert token_body == {"appKey": ROBOT_CODE, "appSecret": TEST_APP_SECRET}
    assert captured[0].get_header("X-acs-dingtalk-access-token") is None
    assert captured[1].get_header("X-acs-dingtalk-access-token") == "tok-robot"
    assert captured[2].get_header("X-acs-dingtalk-access-token") == "tok-robot"
    first_batch = json.loads(captured[1].data.decode("utf-8"))  # type: ignore[union-attr]
    second_batch = json.loads(captured[2].data.decode("utf-8"))  # type: ignore[union-attr]
    assert first_batch["userIds"] == user_ids[:ROBOT_OTO_MAX_USERIDS]
    assert second_batch["userIds"] == [user_ids[ROBOT_OTO_MAX_USERIDS]]


def test_robot_batch_rejects_empty_user_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_token_cache(monkeypatch)
    with pytest.raises(DingTalkApiRequestError, match="不能为空"):
        _ = _client().send_robot_oto_messages(
            robot_code=ROBOT_CODE,
            user_ids=[],
            title="t",
            text="x",
        )


def test_robot_batch_records_invalid_and_flow_controlled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_token_cache(monkeypatch)
    _patch_urlopen(
        monkeypatch,
        responses=[
            _Response(
                json.dumps(
                    {
                        "processQueryKey": "pqk-mix",
                        "invalidStaffIdList": ["bad"],
                        "flowControlledStaffIdList": ["slow"],
                    },
                ).encode(),
            ),
        ],
    )

    result = _client().send_robot_oto_messages(
        robot_code=ROBOT_CODE,
        user_ids=["ok", "bad", "slow"],
        title="t",
        text="x",
    )[0]
    assert result.invalid_staff_ids == frozenset({"bad"})
    assert result.flow_controlled_staff_ids == frozenset({"slow"})
