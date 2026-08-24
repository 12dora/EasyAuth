"""定义应用凭据模型及其静态令牌常量。"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, override

from django.core.exceptions import ValidationError
from django.db import models

from easyauth.applications.credential_capabilities import validate_credential_capabilities

from .app import App

if TYPE_CHECKING:
    from datetime import date, datetime

APP_CREDENTIAL_STATIC_KIND: Final = "static_token"
TOKEN_LOOKUP_REQUIRED_MESSAGE: Final = (
    "静态 token 凭据必须写入 token_lookup(sha256), 否则永远认证失败。"  # noqa: S105 - 提示文案.
)


class AppCredential(models.Model):
    if TYPE_CHECKING:
        id: ClassVar[int]

    app: models.ForeignKey[App, App] = models.ForeignKey(
        App,
        on_delete=models.CASCADE,
        related_name="credentials",
    )
    credential_type: models.CharField[str, str] = models.CharField(max_length=32)
    name: models.CharField[str, str] = models.CharField(max_length=128)
    capabilities: models.JSONField[list[str], list[str]] = models.JSONField(
        default=list,
        blank=True,
        validators=[validate_credential_capabilities],
    )
    token_hash: models.CharField[str, str] = models.CharField(max_length=256)
    # 令牌的确定性查找键(SHA-256), 认证时先索引定位单行再做 PBKDF2 校验,
    # 避免对全部 active 凭据线性跑慢哈希被打成 CPU DoS。
    token_lookup: models.CharField[str, str] = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
    )
    is_active: models.BooleanField[bool, bool] = models.BooleanField(default=True)
    disabled_at: models.DateTimeField[str | date | datetime | None, datetime | None] = (
        models.DateTimeField(blank=True, null=True)
    )
    created_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at: models.DateTimeField[str | date | datetime, datetime] = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering: ClassVar[list[str]] = ["app__app_key", "credential_type", "id"]

    @override
    def __str__(self) -> str:
        return f"{self.app.app_key}:{self.credential_type}:{self.id}"

    @override
    def clean(self) -> None:
        super().clean()
        # 认证强依赖精确匹配 token_lookup=sha256(token); 空值凭据只会静默 401,
        # 属不可能/无效状态, 建号阶段就必须快速失败(BF-1)。
        if self.credential_type == APP_CREDENTIAL_STATIC_KIND and not self.token_lookup:
            raise ValidationError({"token_lookup": TOKEN_LOOKUP_REQUIRED_MESSAGE})
