from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, cast

import pytest
from django.test import Client
from django.utils import timezone

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import DingTalkDirectorySyncState, UserMirror
from easyauth.applications import dependency_health_checks
from easyauth.applications.health_models import DependencyHealthSnapshot
from easyauth.applications.integration_settings import IntegrationSettings
from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryClient,
    AuthentikDirectoryUnavailableError,
)
from easyauth.integrations.authentik.directory_payloads import DingTalkDirectoryStatus
from easyauth.integrations.authentik.liveness import AuthentikLivenessResult

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

CHECK_API_URL: Final = "/console/api/v1/operations/dependency-health/checks"


def test_dependency_health_check_writes_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: 管理员触发一次真实依赖探测(外部探针在测试中被隔离)。
    client = _logged_in_superuser("health-check-admin")
    _ = DingTalkDirectorySyncState.objects.create(
        source_slug="dingtalk",
        corp_id="corp-1",
        status="success",
        counters={"users": 12},
        finished_at=timezone.now().isoformat(),
    )
    monkeypatch.setattr(
        dependency_health_checks,
        "check_authentik_liveness",
        lambda **_kwargs: AuthentikLivenessResult(ok=True, detail="HTTP 204"),
    )
    monkeypatch.setattr(AuthentikDirectoryClient, "get_status", _return_directory_status)
    monkeypatch.setattr(
        dependency_health_checks,
        "_check_celery",
        lambda: dependency_health_checks.DependencyCheckResult(
            dependency="celery",
            status="healthy",
            summary="1 个 worker 响应 ping。",
            error_summary="",
        ),
    )
    settings_row = IntegrationSettings.load()
    settings_row.authentik_api_token = "test-token"  # noqa: S105 - 测试用假 token.
    settings_row.save()

    # When: POST 触发探测。
    response = client.post(CHECK_API_URL)

    # Then: 每个依赖都写入了健康快照并返回最新状态。
    assert response.status_code == HTTPStatus.OK
    payload = cast("dict[str, JsonValue]", response.json())
    health_map = cast("dict[str, dict[str, JsonValue]]", payload["health_map"])
    assert health_map["authentik"]["status"] == "healthy"
    assert health_map["dingtalk"]["status"] == "healthy"
    assert health_map["celery"]["status"] == "healthy"
    assert DependencyHealthSnapshot.objects.filter(dependency="authentik").count() == 1
    assert DependencyHealthSnapshot.objects.filter(dependency="dingtalk").count() == 1
    assert DependencyHealthSnapshot.objects.filter(dependency="celery").count() == 1
    assert DependencyHealthSnapshot.objects.filter(dependency="authentik_directory").count() == 1


def test_dependency_health_check_records_authentik_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _logged_in_superuser("health-check-fail-admin")
    monkeypatch.setattr(
        dependency_health_checks,
        "check_authentik_liveness",
        lambda **_kwargs: AuthentikLivenessResult(ok=False, detail="无法连接 Authentik: refused"),
    )
    monkeypatch.setattr(
        AuthentikDirectoryClient,
        "get_status",
        _raise_directory_unavailable,
    )
    monkeypatch.setattr(
        dependency_health_checks,
        "_check_celery",
        lambda: dependency_health_checks.DependencyCheckResult(
            dependency="celery",
            status="unhealthy",
            summary="无法连接 Celery broker。",
            error_summary="ConnectionError: refused",
        ),
    )

    response = client.post(CHECK_API_URL)

    assert response.status_code == HTTPStatus.OK
    payload = cast("dict[str, JsonValue]", response.json())
    health_map = cast("dict[str, dict[str, JsonValue]]", payload["health_map"])
    assert health_map["authentik"]["status"] == "unhealthy"
    # 未配置钉钉同步时如实提示尚未同步, 不伪造健康结论。
    assert health_map["dingtalk"]["status"] == "warning"
    snapshot = DependencyHealthSnapshot.objects.get(dependency="authentik")
    assert snapshot.status == "unhealthy"
    assert "无法连接" in snapshot.error_summary


def test_dependency_health_check_rejects_get() -> None:
    client = _logged_in_superuser("health-check-method-admin")

    response = client.get(CHECK_API_URL)

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_dependency_health_check_requires_superuser() -> None:
    _ = UserMirror.objects.create(authentik_user_id="health-check-normal-user")
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = "health-check-normal-user"
    session["easyauth_authentik_groups"] = ["Employees"]
    session.save()

    response = client.post(CHECK_API_URL)

    assert response.status_code == HTTPStatus.FORBIDDEN


def _return_directory_status(_self: AuthentikDirectoryClient) -> DingTalkDirectoryStatus:
    return DingTalkDirectoryStatus(source_slug="dingtalk", sync=())


def _raise_directory_unavailable(_self: AuthentikDirectoryClient) -> DingTalkDirectoryStatus:
    message = "Authentik 目录 API 暂不可用。"
    raise AuthentikDirectoryUnavailableError(message)


def _logged_in_superuser(username: str) -> Client:
    _ = UserMirror.objects.create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = username
    session["easyauth_authentik_groups"] = ["EasyAuth Admins"]
    session.save()
    return client
