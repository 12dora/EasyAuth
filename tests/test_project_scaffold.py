from io import StringIO

from django.core.management import call_command
from django.urls import reverse

from easyauth.config.settings import test as project_settings
from easyauth.tasks.grants import GRANT_EXPIRATION_TASK_NAME

GRANT_EXPIRATION_CLEANUP_INTERVAL_SECONDS = 60


def test_project_settings_include_core_apps_when_loaded() -> None:
    # Given: Django 测试配置已由 pytest-django 加载。
    expected_apps = {
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "rest_framework",
        "oauth2_provider",
    }

    # When: 读取已安装应用配置。
    installed_apps = set(project_settings.INSTALLED_APPS)

    # Then: 基础框架应用已启用。
    assert expected_apps <= installed_apps


def test_celery_beat_schedules_grant_expiration_cleanup() -> None:
    # Given: 授权过期清理需要由 Celery beat 周期调度。
    schedule_name = "grant-expiration-cleanup"

    # When: 读取项目 Celery beat 配置。
    schedule = project_settings.CELERY_BEAT_SCHEDULE[schedule_name]

    # Then: beat 调度到 S13 授权过期清理任务。
    assert schedule["task"] == GRANT_EXPIRATION_TASK_NAME
    assert schedule["schedule"] == GRANT_EXPIRATION_CLEANUP_INTERVAL_SECONDS
    assert "easyauth.tasks.grants" in project_settings.CELERY_IMPORTS


def test_webhook_delivery_uses_isolated_queue() -> None:
    route = project_settings.CELERY_TASK_ROUTES["easyauth.webhooks.deliver"]
    assert route["queue"] == "webhooks"


def test_health_endpoint_is_routed_when_project_urls_are_configured() -> None:
    # Given: 项目 URL 配置注册了 health 路由。
    # When: 反解 health 视图名。
    health_path = reverse("health")

    # Then: health 端点被正确路由, 证明 ROOT_URLCONF 已生效。
    assert health_path == "/health/"


def test_manage_check_succeeds_when_project_configuration_is_valid() -> None:
    # Given: Django 配置、应用注册和 URL 配置都已初始化。
    output = StringIO()

    # When: 运行 Django 系统检查。
    check_result = call_command("check", stdout=output, stderr=output)

    # Then: 系统检查没有发现问题。
    assert check_result is None
    assert "System check identified no issues" in output.getvalue()
