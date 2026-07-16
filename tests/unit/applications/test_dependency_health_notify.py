from __future__ import annotations

import pytest

from easyauth.applications import dependency_health_checks
from easyauth.applications.health_models import (
    DEPENDENCY_DINGTALK_NOTIFY,
    DEPENDENCY_HEALTH_STATUS_HEALTHY,
    DEPENDENCY_HEALTH_STATUS_UNHEALTHY,
    DEPENDENCY_HEALTH_STATUS_WARNING,
)
from easyauth.applications.integration_settings import DingTalkRuntimeConfig
from easyauth.applications.models import CAPABILITY_NOTIFY, App, AppCapability

pytestmark = pytest.mark.django_db


def _stub_config(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_key: str,
    app_secret: str,
    agent_id: str,
) -> None:
    config = DingTalkRuntimeConfig(
        app_key=app_key,
        app_secret=app_secret,
        agent_id=agent_id,
        timeout_seconds=5.0,
    )
    monkeypatch.setattr(dependency_health_checks, "dingtalk_runtime_config", lambda: config)


def _make_app_with_notify(*, enabled: bool) -> App:
    app = App.objects.create(app_key="health-notify-app", name="健康检查通知应用")
    _ = AppCapability.objects.create(app=app, capability=CAPABILITY_NOTIFY, enabled=enabled)
    return app


def test_notify_credentials_complete_is_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_config(
        monkeypatch,
        app_key="key",
        app_secret="secret",  # noqa: S106 - 测试专用固定值。
        agent_id="123",
    )
    _ = _make_app_with_notify(enabled=True)

    result = dependency_health_checks._check_dingtalk_notify()  # noqa: SLF001 - 单测直测检查函数。

    assert result.dependency == DEPENDENCY_DINGTALK_NOTIFY
    assert result.status == DEPENDENCY_HEALTH_STATUS_HEALTHY
    assert "1 个应用" in result.summary


def test_notify_missing_agent_id_with_enabled_app_is_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_config(
        monkeypatch,
        app_key="key",
        app_secret="secret",  # noqa: S106 - 测试专用固定值。
        agent_id="",
    )
    _ = _make_app_with_notify(enabled=True)

    result = dependency_health_checks._check_dingtalk_notify()  # noqa: SLF001 - 单测直测检查函数。

    assert result.status == DEPENDENCY_HEALTH_STATUS_UNHEALTHY
    assert "通知凭据缺失" in result.summary
    assert "agent_id" in result.summary


def test_notify_missing_credentials_without_enabled_app_is_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_config(monkeypatch, app_key="", app_secret="", agent_id="")
    _ = _make_app_with_notify(enabled=False)

    result = dependency_health_checks._check_dingtalk_notify()  # noqa: SLF001 - 单测直测检查函数。

    assert result.status == DEPENDENCY_HEALTH_STATUS_WARNING
    assert "无应用开通通知能力" in result.summary


def test_notify_check_included_in_full_run(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_config(
        monkeypatch,
        app_key="key",
        app_secret="secret",  # noqa: S106 - 测试专用固定值。
        agent_id="42",
    )
    snapshots = dependency_health_checks.run_dependency_health_checks()
    assert any(item.component == DEPENDENCY_DINGTALK_NOTIFY for item in snapshots)
