from __future__ import annotations

import os

import pytest
from django.core.exceptions import ImproperlyConfigured

from easyauth.config.settings import base


def test_database_config_uses_sqlite_when_database_url_is_missing_in_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 本地开发显式开启 DEBUG 且未指定 PostgreSQL 连接。
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DJANGO_DEBUG", "1")

    # When: 生成 Django 数据库配置。
    database_config = base.database_config_from_env(os.environ)

    # Then: 开发模式保留 SQLite 默认值。
    default_database = database_config["default"]
    assert default_database["ENGINE"] == "django.db.backends.sqlite3"
    assert default_database["NAME"] == base.BASE_DIR / "db.sqlite3"


def test_database_config_fails_fast_when_database_url_is_missing_in_production() -> None:
    # Given: 生产路径(非 DEBUG)缺失 DATABASE_URL。
    environ: dict[str, str] = {}

    # When / Then: 启动失败, 不允许静默回退到空 SQLite。
    with pytest.raises(ImproperlyConfigured, match="DATABASE_URL"):
        _ = base.database_config_from_env(environ)


def test_required_env_fails_fast_for_missing_secret_key_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 生产路径(非 DEBUG)缺失 DJANGO_SECRET_KEY。
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    monkeypatch.setattr(base, "DEBUG", False)

    # When / Then: 拒绝使用仓库里公开的开发密钥兜底。
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
        _ = base.required_env("DJANGO_SECRET_KEY", dev_default="dev-secret")


def test_database_config_uses_postgresql_when_database_url_is_set() -> None:
    # Given: 本机模拟环境提供 PostgreSQL DATABASE_URL。
    environ = {
        "DATABASE_URL": (
            "postgresql://easyauth:easyauth_dev_password@127.0.0.1:15432/easyauth"
        ),
    }

    # When: 生成 Django 数据库配置。
    database_config = base.database_config_from_env(environ)

    # Then: Django 使用 PostgreSQL 后端和指定连接参数。
    default_database = database_config["default"]
    assert default_database == {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": "127.0.0.1",
        "NAME": "easyauth",
        "PASSWORD": "easyauth_dev_password",
        "PORT": "15432",
        "USER": "easyauth",
    }


def test_database_config_rejects_unsupported_database_url_scheme() -> None:
    # Given: 环境变量使用不受支持的数据库协议。
    environ = {"DATABASE_URL": "mysql://user:password@127.0.0.1:3306/easyauth"}

    # When / Then: 配置加载失败并给出明确错误。
    with pytest.raises(ImproperlyConfigured, match="DATABASE_URL"):
        _ = base.database_config_from_env(environ)
