from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final, cast

import pytest
from django.test import Client
from django.utils import timezone
from pydantic import BaseModel, ConfigDict

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror
from easyauth.applications.ops_models import DependencyHealthSnapshot

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-ops3"
DEPENDENCY_HEALTH_API_URL: Final = "/console/api/v1/operations/dependency-health"


class _HealthItem(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    component: str
    status: str
    last_checked_at: str | None
    summary: str
    error_summary: str
    app_key: str | None = None


class _HealthComponent(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    status: str


class _HealthResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    data: tuple[_HealthItem, ...]
    health_map: dict[str, _HealthComponent]
    authentik: _HealthComponent
    authentik_directory: _HealthComponent
    dingtalk: _HealthComponent
    dingtalk_notify: _HealthComponent
    celery: _HealthComponent


def test_ops3_console_dependency_health_returns_latest_snapshots_without_secrets() -> None:
    # Given: 系统管理员需要查看每个依赖最近一次健康快照。
    client = _logged_in_superuser("ops3-health-snapshot-admin")
    now = timezone.now()
    _ = DependencyHealthSnapshot.objects.create(
        dependency="authentik",
        status="unhealthy",
        checked_at=now - timedelta(minutes=10),
        summary="旧同步失败",
        error_summary="旧错误",
    )
    _ = DependencyHealthSnapshot.objects.create(
        dependency="authentik",
        status="healthy",
        checked_at=now,
        summary="最近同步成功",
    )
    _ = DependencyHealthSnapshot.objects.create(
        dependency="dingtalk",
        status="warning",
        checked_at=now - timedelta(minutes=1),
        summary="最近回调有失败",
        error_summary="Authorization: Bearer abc 密码=def 密钥=ghi 回调失败",
    )
    _ = DependencyHealthSnapshot.objects.create(
        dependency="celery",
        status="healthy",
        checked_at=now - timedelta(minutes=2),
        summary="过期清理完成",
    )

    # When: 管理员读取 dependency health API。
    response = client.get(DEPENDENCY_HEALTH_API_URL)

    # Then: API 返回每个依赖的最新快照, 且敏感字段摘要被隐藏。
    body = response.content.decode()
    payload = _HealthResponse.model_validate_json(body)
    items = {item.component: item for item in payload.data}
    assert response.status_code == HTTPStatus.OK
    assert payload.authentik.status == "healthy"
    assert payload.authentik_directory.status == "unknown"
    assert payload.dingtalk.status == "warning"
    assert payload.dingtalk_notify.status == "unknown"
    assert payload.celery.status == "healthy"
    assert items["authentik"].status == "healthy"
    assert items["authentik"].summary == "最近同步成功"
    assert "旧同步失败" not in body
    assert items["dingtalk"].error_summary == "[已隐藏敏感摘要]"
    assert items["celery"].summary == "过期清理完成"
    assert "client_secret" not in body.lower()
    assert "access_token" not in body.lower()
    assert "abc" not in body
    assert "def" not in body
    assert "authorization" not in body.lower()
    assert "bearer" not in body.lower()
    assert "密码" not in body
    assert "密钥" not in body
    assert "ghi" not in body


def test_dependency_health_includes_authentik_directory_status() -> None:
    client = _logged_in_superuser("ops3-health-directory-admin")
    _ = DependencyHealthSnapshot.objects.create(
        dependency="authentik_directory",
        status="healthy",
        summary="钉钉目录最近同步成功",
    )

    response = client.get(DEPENDENCY_HEALTH_API_URL)

    assert response.status_code == HTTPStatus.OK
    payload = cast("dict[str, JsonValue]", response.json())
    health_map = cast("dict[str, dict[str, JsonValue]]", payload["health_map"])
    assert health_map["authentik_directory"]["status"] == "healthy"
    assert health_map["authentik_directory"]["summary"] == "钉钉目录最近同步成功"


def _logged_in_superuser(username: str) -> Client:
    _ = UserMirror.objects.create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = username
    session["easyauth_authentik_groups"] = ["EasyAuth Admins"]
    session.save()
    return client
