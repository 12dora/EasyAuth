"""设置页三个「测试连接」端点的集成测试(HTTP 出站全部 mock)。"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Self, cast
from urllib.error import HTTPError

import pytest
from django.test import Client

from easyauth.applications.integration_settings import IntegrationSettings
from easyauth.audit.models import AuditLog
from easyauth.integrations.authentik import admin_client as authentik_admin_module
from easyauth.integrations.dingtalk import api_client as dingtalk_module
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    authenticate_console_user,
)

if TYPE_CHECKING:
    from types import TracebackType
    from urllib.request import Request

    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

AUTHENTIK_TEST_URL: Final = "/console/api/v1/settings/integrations/authentik/test"
DINGTALK_TEST_URL: Final = "/console/api/v1/settings/integrations/dingtalk/test"
DINGTALK_NOTIFY_TEST_URL: Final = "/console/api/v1/settings/integrations/dingtalk-notify/test"

AUTHENTIK_USERS_PAGE: Final = b'{"results": [{"uuid": "u-1"}], "pagination": {"count": 1}}'
DINGTALK_ACCESS_TOKEN: Final = b'{"accessToken": "acs-token", "expireIn": 7200}'
OAPI_ACCESS_TOKEN: Final = b'{"errcode": 0, "access_token": "oapi-token", "expires_in": 7200}'

SECRET_DRAFT_TOKEN: Final = "draft-token-never-echoed"


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self._offset = 0

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
        if amount < 0:
            amount = len(self._body) - self._offset
        chunk = self._body[self._offset : self._offset + amount]
        self._offset += len(chunk)
        return chunk

    def getheader(self, _name: str) -> str | None:
        return None


class _Recorder:
    """替换 urlopen: 记录访问过的 URL, 按顺序吐出预置响应或抛出预置异常。"""

    def __init__(self, *outcomes: bytes | Exception) -> None:
        self.urls: list[str] = []
        self._outcomes = list(outcomes)

    def __call__(self, request: Request, timeout: float = 0) -> _Response:
        del timeout
        self.urls.append(request.full_url)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(outcome)


def _install(monkeypatch: pytest.MonkeyPatch, module: object, recorder: _Recorder) -> _Recorder:
    monkeypatch.setattr(module, "urlopen", recorder)
    return recorder


def _admin(username: str) -> Client:
    return authenticate_console_admin(Client(HTTP_HOST="localhost"), username)


def _http_error(code: int) -> HTTPError:
    return HTTPError("https://auth.example.com/api/v3/core/users/", code, "denied", {}, None)  # pyright: ignore[reportArgumentType]


def test_authentik_probe_uses_draft_values_and_reports_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(monkeypatch, authentik_admin_module, _Recorder(AUTHENTIK_USERS_PAGE))
    client = _admin("authentik-probe-ok")

    response = client.post(
        AUTHENTIK_TEST_URL,
        data={
            "authentik_base_url": "https://draft.example.com/",
            "authentik_api_token": SECRET_DRAFT_TOKEN,
        },
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.OK
    body = response.content.decode()
    payload = cast("dict[str, JsonValue]", response.json())
    assert payload["ok"] is True
    assert payload["error_code"] == ""
    assert payload["error_message"] == ""
    assert isinstance(payload["latency_ms"], int)
    # 草稿值优先, 且探针只打一次最小分页。
    assert recorder.urls == ["https://draft.example.com/api/v3/core/users/?page_size=1"]
    # 响应与审计都不得回显 token。
    assert SECRET_DRAFT_TOKEN not in body
    audit = AuditLog.objects.get(event_type="authentik_connectivity_tested")
    assert audit.target_id == "authentik"
    assert audit.metadata["ok"] is True
    assert SECRET_DRAFT_TOKEN not in str(audit.metadata)


def test_authentik_probe_maps_forbidden_to_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    _ = _install(monkeypatch, authentik_admin_module, _Recorder(_http_error(HTTPStatus.FORBIDDEN)))
    client = _admin("authentik-probe-403")

    response = client.post(
        AUTHENTIK_TEST_URL,
        data={"authentik_base_url": "https://draft.example.com", "authentik_api_token": "bad"},
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.OK
    payload = cast("dict[str, JsonValue]", response.json())
    assert payload["ok"] is False
    assert payload["error_code"] == "UNAUTHORIZED"
    assert payload["error_message"]
    audit = AuditLog.objects.get(event_type="authentik_connectivity_tested")
    assert audit.metadata["error_code"] == "UNAUTHORIZED"


def test_authentik_probe_falls_back_to_stored_row(monkeypatch: pytest.MonkeyPatch) -> None:
    _ = IntegrationSettings.objects.create(
        pk=1,
        authentik_base_url="https://stored.example.com",
        authentik_api_token="stored-token",
    )
    recorder = _install(monkeypatch, authentik_admin_module, _Recorder(AUTHENTIK_USERS_PAGE))
    client = _admin("authentik-probe-stored")

    response = client.post(AUTHENTIK_TEST_URL, data={}, content_type="application/json")

    assert response.status_code == HTTPStatus.OK
    assert cast("dict[str, JsonValue]", response.json())["ok"] is True
    assert recorder.urls == ["https://stored.example.com/api/v3/core/users/?page_size=1"]


def test_authentik_probe_reports_missing_token_without_calling_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(monkeypatch, authentik_admin_module, _Recorder())
    client = _admin("authentik-probe-missing")

    response = client.post(AUTHENTIK_TEST_URL, data={}, content_type="application/json")

    payload = cast("dict[str, JsonValue]", response.json())
    assert payload["ok"] is False
    assert payload["error_code"] == "NOT_CONFIGURED"
    assert recorder.urls == []


def test_authentik_probe_rejects_plaintext_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _install(monkeypatch, authentik_admin_module, _Recorder())
    client = _admin("authentik-probe-insecure")

    response = client.post(
        AUTHENTIK_TEST_URL,
        data={"authentik_base_url": "http://auth.example.com", "authentik_api_token": "t"},
        content_type="application/json",
    )

    payload = cast("dict[str, JsonValue]", response.json())
    assert payload["ok"] is False
    assert payload["error_code"] == "INSECURE_BASE_URL"
    assert recorder.urls == []


def test_authentik_probe_requires_superuser() -> None:
    client = authenticate_console_user(Client(HTTP_HOST="localhost"), "authentik-probe-user")

    response = client.post(AUTHENTIK_TEST_URL, data={}, content_type="application/json")

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_authentik_probe_rejects_get() -> None:
    client = _admin("authentik-probe-get")

    response = client.get(AUTHENTIK_TEST_URL)

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_authentik_probe_rejects_unknown_field() -> None:
    client = _admin("authentik-probe-extra")

    response = client.post(
        AUTHENTIK_TEST_URL,
        data={"unexpected": "x"},
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_dingtalk_app_probe_uses_draft_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _install(monkeypatch, dingtalk_module, _Recorder(DINGTALK_ACCESS_TOKEN))
    client = _admin("dingtalk-probe-ok")

    response = client.post(
        DINGTALK_TEST_URL,
        data={"dingtalk_app_key": "draft-key", "dingtalk_app_secret": "draft-secret"},
        content_type="application/json",
    )

    payload = cast("dict[str, JsonValue]", response.json())
    assert payload["ok"] is True
    # 统一认证应用只验新版换票, 不再顺带探测服务号(服务号有独立端点)。
    assert recorder.urls == ["https://api.dingtalk.com/v1.0/oauth2/accessToken"]
    assert AuditLog.objects.filter(event_type="dingtalk_connectivity_tested").count() == 1


def test_dingtalk_notify_probe_checks_both_token_apis(monkeypatch: pytest.MonkeyPatch) -> None:
    _ = IntegrationSettings.objects.create(
        pk=1,
        dingtalk_app_key="main-key",
        dingtalk_app_secret="main-secret",
        dingtalk_agent_id="1001",
        dingtalk_notify_app_key="svc-key",
        dingtalk_notify_app_secret="svc-secret",
        dingtalk_notify_agent_id="9001",
    )
    recorder = _install(
        monkeypatch,
        dingtalk_module,
        _Recorder(DINGTALK_ACCESS_TOKEN, OAPI_ACCESS_TOKEN),
    )
    client = _admin("notify-probe-ok")

    response = client.post(DINGTALK_NOTIFY_TEST_URL, data={}, content_type="application/json")

    payload = cast("dict[str, JsonValue]", response.json())
    assert payload["ok"] is True
    assert recorder.urls == [
        "https://api.dingtalk.com/v1.0/oauth2/accessToken",
        "https://oapi.dingtalk.com/gettoken?appkey=svc-key&appsecret=svc-secret",
    ]
    audit = AuditLog.objects.get(event_type="dingtalk_notify_connectivity_tested")
    assert audit.target_id == "dingtalk_notify"


def test_dingtalk_notify_probe_reports_oapi_business_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = IntegrationSettings.objects.create(
        pk=1,
        dingtalk_notify_app_key="svc-key",
        dingtalk_notify_app_secret="svc-secret",
        dingtalk_notify_agent_id="9001",
    )
    _ = _install(
        monkeypatch,
        dingtalk_module,
        _Recorder(DINGTALK_ACCESS_TOKEN, b'{"errcode": 40089, "errmsg": "invalid appsecret"}'),
    )
    client = _admin("notify-probe-errcode")

    response = client.post(DINGTALK_NOTIFY_TEST_URL, data={}, content_type="application/json")

    payload = cast("dict[str, JsonValue]", response.json())
    assert payload["ok"] is False
    assert payload["error_code"] == "REJECTED"
    assert "invalid appsecret" in str(payload["error_message"])


def test_dingtalk_notify_probe_falls_back_to_main_app_when_triple_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = IntegrationSettings.objects.create(
        pk=1,
        dingtalk_app_key="main-key",
        dingtalk_app_secret="main-secret",
        dingtalk_agent_id="1001",
        dingtalk_notify_app_key="svc-key",
    )
    recorder = _install(
        monkeypatch,
        dingtalk_module,
        _Recorder(DINGTALK_ACCESS_TOKEN, OAPI_ACCESS_TOKEN),
    )
    client = _admin("notify-probe-fallback")

    response = client.post(DINGTALK_NOTIFY_TEST_URL, data={}, content_type="application/json")

    assert cast("dict[str, JsonValue]", response.json())["ok"] is True
    # 服务号三元组未配齐 = 运行时回退主应用, 探针必须打主应用凭证。
    assert recorder.urls[1] == (
        "https://oapi.dingtalk.com/gettoken?appkey=main-key&appsecret=main-secret"
    )


def test_dingtalk_notify_probe_reports_missing_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _install(monkeypatch, dingtalk_module, _Recorder())
    client = _admin("notify-probe-missing")

    response = client.post(DINGTALK_NOTIFY_TEST_URL, data={}, content_type="application/json")

    payload = cast("dict[str, JsonValue]", response.json())
    assert payload["ok"] is False
    assert payload["error_code"] == "NOT_CONFIGURED"
    assert recorder.urls == []


def test_dingtalk_notify_probe_maps_network_failure_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = IntegrationSettings.objects.create(
        pk=1,
        dingtalk_notify_app_key="svc-key",
        dingtalk_notify_app_secret="svc-secret",
        dingtalk_notify_agent_id="9001",
    )
    _ = _install(monkeypatch, dingtalk_module, _Recorder(TimeoutError("timed out")))
    client = _admin("notify-probe-timeout")

    response = client.post(DINGTALK_NOTIFY_TEST_URL, data={}, content_type="application/json")

    payload = cast("dict[str, JsonValue]", response.json())
    assert payload["ok"] is False
    assert payload["error_code"] == "UNAVAILABLE"


def test_dingtalk_notify_probe_requires_superuser() -> None:
    client = authenticate_console_user(Client(HTTP_HOST="localhost"), "notify-probe-user")

    response = client.post(DINGTALK_NOTIFY_TEST_URL, data={}, content_type="application/json")

    assert response.status_code == HTTPStatus.FORBIDDEN
