from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Final
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

if TYPE_CHECKING:
    from collections.abc import Mapping

BASE_DIR: Final = Path(__file__).resolve().parents[4]

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

MISSING_SETTING_ERROR_TEMPLATE: Final = (
    "{name} 未配置。生产环境必须显式设置该环境变量; 本地开发请设置 DJANGO_DEBUG=1。"
)


def required_env(name: str, *, dev_default: str) -> str:
    # 生产环境缺失关键配置必须启动失败, 只有显式 DEBUG 模式才允许开发默认值。
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if DEBUG:
        return dev_default
    raise ImproperlyConfigured(MISSING_SETTING_ERROR_TEMPLATE.format(name=name))


SECRET_KEY = required_env(
    "DJANGO_SECRET_KEY",
    dev_default="django-insecure-easyauth-local-dev-only",
)
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS: list[str] = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "oauth2_provider",
    "easyauth.config.apps.EasyAuthConfig",
    "easyauth.applications.apps.ApplicationsConfig",
    "easyauth.accounts.apps.AccountsConfig",
    "easyauth.audit.apps.AuditConfig",
    "easyauth.access_requests.apps.AccessRequestsConfig",
    "easyauth.grants.apps.GrantsConfig",
    "easyauth.portal.apps.PortalConfig",
    "easyauth.admin_console.apps.AdminConsoleConfig",
]

MIDDLEWARE: list[str] = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "easyauth.config.middleware.SafeNotFoundMiddleware",
]

ROOT_URLCONF = "easyauth.config.urls"
WSGI_APPLICATION = "easyauth.config.wsgi.application"
ASGI_APPLICATION = "easyauth.config.asgi.application"

TemplateConfig = dict[str, bool | str | list[str] | dict[str, list[str]]]

TEMPLATES: list[TemplateConfig] = [
    {
        "APP_DIRS": True,
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DatabaseSettingValue = str | Path
DatabaseConfig = dict[str, DatabaseSettingValue]
DatabaseSettings = dict[str, DatabaseConfig]
DATABASE_URL_SCHEME_ERROR: Final = "DATABASE_URL 只支持 postgres 或 postgresql 协议。"
DATABASE_URL_HOST_ERROR: Final = "DATABASE_URL 必须包含 PostgreSQL host。"
DATABASE_URL_NAME_ERROR: Final = "DATABASE_URL 必须包含 PostgreSQL database name。"
DATABASE_URL_PORT_ERROR: Final = "DATABASE_URL 包含无效 PostgreSQL port。"
DATABASE_URL_REQUIRED_ERROR: Final = (
    "DATABASE_URL 未配置。生产环境不允许静默回退 SQLite; 本地开发请设置 DJANGO_DEBUG=1。"
)


def database_config_from_env(environ: Mapping[str, str]) -> DatabaseSettings:
    database_url = environ.get("DATABASE_URL", "").strip()
    if database_url == "":
        # 生产路径缺失数据库配置必须启动失败, 否则 IAM 会静默跑在空 SQLite 上。
        if environ.get("DJANGO_DEBUG", "0") != "1":
            raise ImproperlyConfigured(DATABASE_URL_REQUIRED_ERROR)
        return {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": BASE_DIR / "db.sqlite3",
            },
        }
    return {"default": _postgres_database_config(database_url)}


def _postgres_database_config(database_url: str) -> DatabaseConfig:
    parsed_url = urlparse(database_url)
    if parsed_url.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured(DATABASE_URL_SCHEME_ERROR)
    if parsed_url.hostname is None:
        raise ImproperlyConfigured(DATABASE_URL_HOST_ERROR)
    database_name = unquote(parsed_url.path.lstrip("/"))
    if database_name == "":
        raise ImproperlyConfigured(DATABASE_URL_NAME_ERROR)

    try:
        port = parsed_url.port
    except ValueError as exc:
        raise ImproperlyConfigured(DATABASE_URL_PORT_ERROR) from exc

    config: DatabaseConfig = {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": parsed_url.hostname,
        "NAME": database_name,
        "PASSWORD": unquote(parsed_url.password or ""),
        "USER": unquote(parsed_url.username or ""),
    }
    if port is not None:
        config["PORT"] = str(port)
    return config


DATABASES = database_config_from_env(os.environ)

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
if not DEBUG:
    # TLS 终止在反向代理; 不设该头会让 is_secure() 恒为 False,
    # /auth/login/ 的 canonical 比对会陷入 302 死循环。
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "3600"))
    SECURE_CONTENT_TYPE_NOSNIFF = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "src" / "easyauth" / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK: dict[str, list[str]] = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
}

OAUTH2_PROVIDER_APPLICATION_MODEL = "oauth2_provider.Application"
EASYAUTH_AUTHENTIK_OIDC_ISSUER = os.environ.get(
    "EASYAUTH_AUTHENTIK_OIDC_ISSUER",
    "https://authentik.localhost/application/o/easyauth/",
)
EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT = os.environ.get(
    "EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT",
    "",
)
EASYAUTH_AUTHENTIK_LOGOUT_URL = os.environ.get(
    "EASYAUTH_AUTHENTIK_LOGOUT_URL",
    "",
)
EASYAUTH_AUTHENTIK_POST_LOGOUT_REDIRECT_URI = os.environ.get(
    "EASYAUTH_AUTHENTIK_POST_LOGOUT_REDIRECT_URI",
    "",
)
EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID = os.environ.get(
    "EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID",
    "easyauth-portal",
)
EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET = os.environ.get(
    "EASYAUTH_AUTHENTIK_OIDC_CLIENT_SECRET",
    "",
)
EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI = os.environ.get(
    "EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI",
    "http://localhost:8000/auth/callback/",
)
EASYAUTH_AUTHENTIK_OIDC_TOKEN_ENDPOINT = os.environ.get(
    "EASYAUTH_AUTHENTIK_OIDC_TOKEN_ENDPOINT",
    "https://authentik.localhost/application/o/token/",
)
EASYAUTH_AUTHENTIK_OIDC_JWKS_URL = os.environ.get(
    "EASYAUTH_AUTHENTIK_OIDC_JWKS_URL",
    "https://authentik.localhost/application/o/easyauth/jwks/",
)
EASYAUTH_AUTHENTIK_OIDC_SCOPES = tuple(
    scope
    for scope in os.environ.get(
        "EASYAUTH_AUTHENTIK_OIDC_SCOPES",
        "openid profile email",
    ).split()
    if scope
)
EASYAUTH_AUTHENTIK_OIDC_SIGNING_ALGORITHMS = tuple(
    algorithm
    for algorithm in os.environ.get(
        "EASYAUTH_AUTHENTIK_OIDC_SIGNING_ALGORITHMS",
        "RS256",
    ).split()
    if algorithm
)
EASYAUTH_AUTHENTIK_OIDC_HTTP_TIMEOUT_SECONDS = float(
    os.environ.get("EASYAUTH_AUTHENTIK_OIDC_HTTP_TIMEOUT_SECONDS", "5"),
)
EASYAUTH_ENABLE_DEV_LOGIN = os.environ.get("EASYAUTH_ENABLE_DEV_LOGIN", "0") == "1"
EASYAUTH_CONSOLE_SUPERUSER_GROUPS = tuple(
    group.strip()
    for group in os.environ.get("EASYAUTH_CONSOLE_SUPERUSER_GROUPS", "EasyAuth Admins").split(",")
    if group.strip()
)
EASYAUTH_CONSOLE_SUPERUSER_IDS = tuple(
    user_id.strip()
    for user_id in os.environ.get("EASYAUTH_CONSOLE_SUPERUSER_IDS", "").split(",")
    if user_id.strip()
)
EASYAUTH_PERMISSION_QUERY_CACHE_TTL_SECONDS = 300
EASYAUTH_DINGTALK_CALLBACK_SECRET = os.environ.get("EASYAUTH_DINGTALK_CALLBACK_SECRET", "")
EASYAUTH_AUTHENTIK_BASE_URL = required_env(
    "EASYAUTH_AUTHENTIK_BASE_URL",
    dev_default="http://localhost:19000",
).rstrip("/")
EASYAUTH_AUTHENTIK_API_TOKEN = required_env("EASYAUTH_AUTHENTIK_API_TOKEN", dev_default="")
EASYAUTH_AUTHENTIK_DINGTALK_SOURCE_SLUG = os.environ.get(
    "EASYAUTH_AUTHENTIK_DINGTALK_SOURCE_SLUG",
    "dingtalk",
)

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_IMPORTS = ("easyauth.tasks.grants", "easyauth.tasks.authentik", "easyauth.tasks.health")
CELERY_BEAT_SCHEDULE: dict[str, dict[str, str | float]] = {
    "grant-expiration-cleanup": {
        "task": "easyauth.grants.cleanup_expired_grants",
        "schedule": float(os.environ.get("EASYAUTH_GRANT_EXPIRATION_CLEANUP_SECONDS", "60")),
    },
    # 钉钉目录同步兼离职回收: 把 Authentik 镜像的组织事实回灌 UserMirror 并撤销离职授权。
    "dingtalk-directory-sync": {
        "task": "easyauth.authentik.sync_dingtalk_directory",
        "schedule": float(os.environ.get("EASYAUTH_DINGTALK_DIRECTORY_SYNC_SECONDS", "300")),
    },
    # 上游依赖健康探测: Authentik 存活/目录 API/钉钉同步链路/Celery worker。
    "dependency-health-check": {
        "task": "easyauth.health.run_dependency_health_checks",
        "schedule": float(os.environ.get("EASYAUTH_DEPENDENCY_HEALTH_CHECK_SECONDS", "300")),
    },
}
