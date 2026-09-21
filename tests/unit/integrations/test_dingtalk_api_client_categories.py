from __future__ import annotations

import sys
import types
from contextlib import suppress
from typing import TYPE_CHECKING, Self

import pytest
from django.core.cache import cache

from easyauth.integrations.dingtalk import api_client as client_module
from easyauth.integrations.dingtalk.access_token import (
    access_token_cache_key,
    cache_access_token,
)
from easyauth.integrations.dingtalk.api_client import (
    DingTalkApiClient,
    DingTalkApiRequestError,
    DingTalkCallBudgetExceededError,
    DingTalkCallCategory,
    DingTalkFormComponent,
)
from easyauth.usage.recorder import current_hour_counts

if TYPE_CHECKING:
    from types import TracebackType
    from urllib.request import Request

    from easyauth.usage.registry import UsageCategory

TEST_APP_SECRET = "app-secret"
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


def _client() -> DingTalkApiClient:
    return DingTalkApiClient(app_key="app-key", app_secret=TEST_APP_SECRET, timeout_seconds=5)


def _seed_token() -> None:
    cache_access_token(
        cache,
        access_token_cache_key("app-key", TEST_APP_SECRET),
        CACHED_TOKEN,
        expire_seconds=7200,
    )


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, *bodies: bytes) -> list[Request]:
    captured: list[Request] = []
    responses = iter(_Response(body) for body in bodies)

    def fake_urlopen(request: Request, *, timeout: float) -> _Response:
        del timeout
        captured.append(request)
        return next(responses)

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    return captured


def _patch_decide(monkeypatch: pytest.MonkeyPatch, *, allowed: bool) -> None:
    name = "easyauth.usage.enforcement"
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)

    def _decide(_spec: UsageCategory) -> bool:
        return allowed

    monkeypatch.setattr(f"{name}.decide", _decide, raising=False)


def _spy_categories(monkeypatch: pytest.MonkeyPatch) -> list[DingTalkCallCategory]:
    recorded: list[DingTalkCallCategory] = []
    original = client_module.record_and_check

    def spy(category: DingTalkCallCategory) -> None:
        recorded.append(category)
        original(category)

    monkeypatch.setattr(client_module, "record_and_check", spy)
    return recorded


def test_cached_token_does_not_meter(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_decide(monkeypatch, allowed=True)
    _seed_token()
    assert _client().get_access_token() == CACHED_TOKEN
    assert current_hour_counts() == {}


def test_get_access_token_meters_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_decide(monkeypatch, allowed=True)
    recorded = _spy_categories(monkeypatch)
    _ = _patch_urlopen(monkeypatch, b'{"accessToken":"tok","expireIn":7200}')
    assert _client().get_access_token(force_refresh=True) == "tok"
    assert recorded == ["token"]
    assert current_hour_counts()["token"] == (1, 0)


def test_create_and_get_process_instance_meter_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_decide(monkeypatch, allowed=True)
    _seed_token()
    recorded = _spy_categories(monkeypatch)
    _ = _patch_urlopen(
        monkeypatch,
        b'{"instanceId":"proc-1"}',
        b'{"result":{"status":"RUNNING"}}',
    )
    client = _client()
    instance_id = client.create_process_instance(
        process_code="PROC",
        originator_userid="u1",
        form_components=(DingTalkFormComponent(name="标题", value="v"),),
    )
    payload = client.get_process_instance(instance_id)
    assert instance_id == "proc-1"
    assert payload["status"] == "RUNNING"
    assert recorded == ["approval", "approval"]


def test_send_work_notification_meters_notify_send(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_decide(monkeypatch, allowed=True)
    _seed_token()
    recorded = _spy_categories(monkeypatch)
    _ = _patch_urlopen(monkeypatch, b'{"errcode":0,"task_id":99}')
    task_id = _client().send_work_notification(
        agent_id=1,
        userid_list=["u1"],
        msg={"msgtype": "text", "text": {"content": "hi"}},
    )
    assert task_id == "99"
    assert recorded == ["notify_send"]


def test_get_send_progress_and_result_meter_notify_reconcile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_decide(monkeypatch, allowed=True)
    _seed_token()
    recorded = _spy_categories(monkeypatch)
    _ = _patch_urlopen(
        monkeypatch,
        b'{"errcode":0,"progress":{"status":2,"progress_in_percent":100}}',
        (
            b'{"errcode":0,"send_result":{"read_user_id_list":[],'
            b'"unread_user_id_list":[],"invalid_user_id_list":[],'
            b'"failed_user_id_list":[],"forbidden_user_id_list":[],'
            b'"forbidden_list":[]}}'
        ),
    )
    client = _client()
    # 计量发生在 HTTP 之前; 回执字段契约由另一路并行修改, 解析失败不影响类别断言。
    with suppress(DingTalkApiRequestError):
        _ = client.get_send_progress(agent_id=1, task_id="42")
    with suppress(DingTalkApiRequestError):
        _ = client.get_send_result(agent_id=1, task_id="42")
    assert recorded == ["notify_reconcile", "notify_reconcile"]


def test_robot_batch_send_meters_robot_send(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_decide(monkeypatch, allowed=True)
    _seed_token()
    recorded = _spy_categories(monkeypatch)
    _ = _patch_urlopen(
        monkeypatch,
        b'{"processQueryKey":"pqk","invalidStaffIdList":[],"flowControlledStaffIdList":[]}',
    )
    results = _client().send_robot_oto_messages(
        robot_code="app-key",
        user_ids=["u1"],
        title="标题",
        text="正文",
    )
    assert len(results) == 1
    assert recorded == ["robot_send"]


def test_probe_oapi_access_token_meters_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_decide(monkeypatch, allowed=True)
    recorded = _spy_categories(monkeypatch)
    _ = _patch_urlopen(monkeypatch, b'{"errcode":0,"access_token":"oapi-tok"}')
    _client().probe_oapi_access_token()
    assert recorded == ["probe"]


def test_budget_exceeded_skips_http(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_decide(monkeypatch, allowed=False)
    called: list[int] = []

    def boom(request: Request, *, timeout: float) -> _Response:
        del request, timeout
        called.append(1)
        message = "预算超限后不得发 HTTP。"
        raise AssertionError(message)

    monkeypatch.setattr(client_module, "urlopen", boom)
    with pytest.raises(DingTalkCallBudgetExceededError):
        _ = _client().get_access_token(force_refresh=True)
    assert called == []
