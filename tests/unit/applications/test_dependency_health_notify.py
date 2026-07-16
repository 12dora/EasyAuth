from __future__ import annotations

import pytest

from easyauth.applications import dependency_health_checks
from easyauth.applications.health_models import (
    DEPENDENCY_DINGTALK_NOTIFY,
    DEPENDENCY_HEALTH_STATUS_HEALTHY,
    DEPENDENCY_HEALTH_STATUS_UNHEALTHY,
)
from easyauth.applications.models import (
    CAPABILITY_NOTIFY,
    App,
    AppCapability,
    AppNotificationChannel,
)

pytestmark = pytest.mark.django_db


def _make_app_with_notify(*, app_key: str, enabled: bool) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppCapability.objects.create(app=app, capability=CAPABILITY_NOTIFY, enabled=enabled)
    return app


def _create_channel(app: App) -> AppNotificationChannel:
    return AppNotificationChannel.objects.create(
        app=app,
        name="健康检查通道",
        dingtalk_app_key="key",
        dingtalk_app_secret="secret",  # noqa: S106 - 测试专用固定值。
        agent_id="123",
        directory_source_slug="dingtalk",
        corp_id="health-corp",
        version=1,
    )


def test_all_notify_apps_have_active_channels_is_healthy() -> None:
    app = _make_app_with_notify(app_key="health-notify-app", enabled=True)
    _ = _create_channel(app)

    result = dependency_health_checks.check_dingtalk_notify()

    assert result.dependency == DEPENDENCY_DINGTALK_NOTIFY
    assert result.status == DEPENDENCY_HEALTH_STATUS_HEALTHY
    assert "1 个通知应用" in result.summary


def test_enabled_app_without_active_channel_is_unhealthy() -> None:
    _ = _make_app_with_notify(app_key="missing-channel", enabled=True)

    result = dependency_health_checks.check_dingtalk_notify()

    assert result.status == DEPENDENCY_HEALTH_STATUS_UNHEALTHY
    assert "missing-channel" in result.summary


def test_no_enabled_notify_app_is_healthy() -> None:
    _ = _make_app_with_notify(app_key="notify-disabled", enabled=False)

    result = dependency_health_checks.check_dingtalk_notify()

    assert result.status == DEPENDENCY_HEALTH_STATUS_HEALTHY
    assert "无 active 应用" in result.summary


def test_one_missing_channel_cannot_be_hidden_by_another_app() -> None:
    configured = _make_app_with_notify(app_key="configured", enabled=True)
    _ = _create_channel(configured)
    _ = _make_app_with_notify(app_key="not-configured", enabled=True)

    result = dependency_health_checks.check_dingtalk_notify()

    assert result.status == DEPENDENCY_HEALTH_STATUS_UNHEALTHY
    assert "not-configured" in result.summary


def test_notify_check_included_in_full_run() -> None:
    app = _make_app_with_notify(app_key="full-run-notify", enabled=True)
    _ = _create_channel(app)
    snapshots = dependency_health_checks.run_dependency_health_checks()
    assert any(item.component == DEPENDENCY_DINGTALK_NOTIFY for item in snapshots)
