from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final, override

from django.conf import settings
from django.db import models
from django.db.models import Q

if TYPE_CHECKING:
    from datetime import date, datetime

INTEGRATION_SETTINGS_SINGLETON_ID: Final = 1

AUTHENTIK_CONFIG_SOURCE_OVERRIDE: Final = "override"
AUTHENTIK_CONFIG_SOURCE_ENV: Final = "env"
AUTHENTIK_CONFIG_SOURCE_MISSING: Final = "missing"


class IntegrationSettings(models.Model):
    # 上游集成的运行时设置(单行), 空字段回退到环境变量配置。

    if TYPE_CHECKING:
        id: ClassVar[int]

    authentik_base_url: models.CharField[str, str] = models.CharField(
        max_length=512,
        blank=True,
    )
    authentik_api_token: models.CharField[str, str] = models.CharField(
        max_length=512,
        blank=True,
    )
    updated_by: models.CharField[str, str] = models.CharField(max_length=128, blank=True)
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(id=INTEGRATION_SETTINGS_SINGLETON_ID),
                name="applications_integration_settings_singleton",
            ),
        ]

    @override
    def __str__(self) -> str:
        return f"integration-settings:{self.id}"

    @classmethod
    def load(cls) -> IntegrationSettings:
        row, _ = cls.objects.get_or_create(pk=INTEGRATION_SETTINGS_SINGLETON_ID)
        return row


@dataclass(frozen=True, slots=True)
class AuthentikRuntimeConfig:
    base_url: str
    api_token: str
    source_slug: str
    timeout_seconds: float
    base_url_source: str
    api_token_source: str


def authentik_runtime_config() -> AuthentikRuntimeConfig:
    # 解析 Authentik 集成生效配置: 数据库设置优先, 其次环境变量。
    row = IntegrationSettings.objects.filter(pk=INTEGRATION_SETTINGS_SINGLETON_ID).first()
    override_base_url = row.authentik_base_url.strip() if row is not None else ""
    override_api_token = row.authentik_api_token.strip() if row is not None else ""
    env_base_url = str(getattr(settings, "EASYAUTH_AUTHENTIK_BASE_URL", "")).strip()
    env_api_token = str(getattr(settings, "EASYAUTH_AUTHENTIK_API_TOKEN", "")).strip()
    base_url = override_base_url or env_base_url
    api_token = override_api_token or env_api_token
    return AuthentikRuntimeConfig(
        base_url=base_url.rstrip("/"),
        api_token=api_token,
        source_slug=str(
            getattr(settings, "EASYAUTH_AUTHENTIK_DINGTALK_SOURCE_SLUG", "dingtalk"),
        ),
        timeout_seconds=float(
            getattr(settings, "EASYAUTH_AUTHENTIK_OIDC_HTTP_TIMEOUT_SECONDS", 5),
        ),
        base_url_source=_source(override=override_base_url, env=env_base_url),
        api_token_source=_source(override=override_api_token, env=env_api_token),
    )


def _source(*, override: str, env: str) -> str:
    if override:
        return AUTHENTIK_CONFIG_SOURCE_OVERRIDE
    if env:
        return AUTHENTIK_CONFIG_SOURCE_ENV
    return AUTHENTIK_CONFIG_SOURCE_MISSING
