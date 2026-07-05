from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final, override

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from easyauth.config.crypto import EncryptedCharField
from easyauth.config.net import InsecureUrlError, require_secure_url

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
    # 高权限管理 token 静态加密落库; 密文比明文长, 需更大的列宽。
    authentik_api_token: EncryptedCharField = EncryptedCharField(
        max_length=1024,
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

    @override
    def clean(self) -> None:
        super().clean()
        base_url = self.authentik_base_url.strip()
        if base_url:
            # 管理 token 以 Authorization: Bearer 头发送, base_url 明文 http 会导致 token 明文传输。
            try:
                require_secure_url(base_url, allow_local_http=True)
            except InsecureUrlError as error:
                raise ValidationError({"authentik_base_url": str(error)}) from error

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
    base_url = (override_base_url or env_base_url).rstrip("/")
    api_token = override_api_token or env_api_token
    # 注: 这里不对 base_url 抛错(该函数被设置页 GET/健康探测/目录客户端等只读路径调用,
    # 抛错会让设置页 500 并连累健康快照)。写入边界(model.clean + 设置 API 校验)已挡明文 http;
    # 实际发送管理 token 的边界(directory_client 请求)会再强制 https, 见 base_url_is_secure。
    return AuthentikRuntimeConfig(
        base_url=base_url,
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
