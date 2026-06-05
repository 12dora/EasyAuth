from io import StringIO

from django.core.management import call_command
from django.urls import get_resolver

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


def test_celery_uses_eager_mode_when_tests_run() -> None:
    # Given: 测试环境需要同步执行 Celery 任务。
    expected_eager_mode = True

    # When: 读取 Celery 测试配置。
    eager_mode = project_settings.CELERY_TASK_ALWAYS_EAGER

    # Then: Celery 任务在测试中 eager 执行。
    assert eager_mode is expected_eager_mode


def test_celery_beat_schedules_grant_expiration_cleanup() -> None:
    # Given: 授权过期清理需要由 Celery beat 周期调度。
    schedule_name = "grant-expiration-cleanup"

    # When: 读取项目 Celery beat 配置。
    schedule = project_settings.CELERY_BEAT_SCHEDULE[schedule_name]

    # Then: beat 调度到 S13 授权过期清理任务。
    assert schedule["task"] == GRANT_EXPIRATION_TASK_NAME
    assert schedule["schedule"] == GRANT_EXPIRATION_CLEANUP_INTERVAL_SECONDS
    assert "easyauth.tasks.grants" in project_settings.CELERY_IMPORTS


def test_url_resolver_loads_when_project_urls_are_configured() -> None:
    # Given: Django ROOT_URLCONF 指向项目 URL 模块。
    expected_urlconf = "easyauth.config.urls"

    # When: 加载 URL resolver。
    resolver = get_resolver()

    # Then: resolver 绑定到项目 URL 模块。
    assert resolver.urlconf_name == expected_urlconf


def test_manage_check_succeeds_when_project_configuration_is_valid() -> None:
    # Given: Django 配置、应用注册和 URL 配置都已初始化。
    output = StringIO()

    # When: 运行 Django 系统检查。
    check_result = call_command("check", stdout=output, stderr=output)

    # Then: 系统检查没有发现问题。
    assert check_result is None
    assert "System check identified no issues" in output.getvalue()
