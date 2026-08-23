from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar, Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from easyauth.applications.models import CAPABILITY_VALUES

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# 顶层 capabilities 节: 平台能力申明白名单; 未知值仅告警不拒绝(向前兼容新 SDK)。
_PLATFORM_CAPABILITY_EMPTY_MESSAGE: Final = "capabilities 元素必须是非空字符串。"


class AppPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    app_key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    is_active: bool = True


class ScopePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    name_en: str = Field(default="", max_length=128)
    description: str = ""
    description_en: str = ""
    is_active: bool = True
    display_order: int = 0


class PermissionGroupPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    name_en: str = Field(default="", max_length=128)
    description: str = ""
    description_en: str = ""
    parent_key: str = ""
    display_order: int = 0
    is_active: bool = True


class PermissionPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    name_en: str = Field(default="", max_length=128)
    description: str = ""
    description_en: str = ""
    group_key: str = Field(min_length=1, max_length=128)
    supported_scopes: tuple[str, ...] = Field(min_length=1)
    risk_level: str = "standard"
    is_active: bool = True


class GrantPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    permission: str = Field(min_length=1, max_length=128)
    scope: str = Field(min_length=1, max_length=64)
    is_active: bool = True


class AuthorizationGroupPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=64)
    kind: Literal["role", "bundle"]
    name: str = Field(min_length=1, max_length=128)
    name_en: str = Field(default="", max_length=128)
    description: str = ""
    description_en: str = ""
    requestable: bool = True
    is_active: bool = True
    grants: tuple[GrantPayload, ...] = ()


class ApprovalRulePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    target_type: Literal["authorization_group", "permission"]
    target_key: str = Field(min_length=1, max_length=128)
    approver_userids: tuple[str, ...] = Field(min_length=1)
    is_active: bool = True


class HandoverAssetTypePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    type: str = Field(min_length=1, max_length=64)
    label: str = Field(default="", max_length=120)
    detail_supported: bool = False
    releasable: bool = False


class LifecyclePayload(BaseModel):
    # 下游生命周期交接声明(与 easyauth-app-sdk 描述符契约一致): URL 允许绝对地址
    # 或以 / 开头的站内路径(自动接入时用下游 base_url 补全)。
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    handover_url: str | None = Field(default=None, max_length=512)
    onboard_url: str | None = Field(default=None, max_length=512)
    capabilities: tuple[str, ...] = ()
    handover_asset_types: tuple[HandoverAssetTypePayload, ...] = ()


class WebhookPayload(BaseModel):
    # 下游 webhook 验签方式声明; 目前契约只支持 hmac-sha256。
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    signing: Literal["hmac-sha256"] = "hmac-sha256"


class AppManifestPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(ge=1)
    app: AppPayload
    scopes: tuple[ScopePayload, ...] = Field(min_length=1)
    permission_groups: tuple[PermissionGroupPayload, ...] = ()
    permissions: tuple[PermissionPayload, ...] = ()
    authorization_groups: tuple[AuthorizationGroupPayload, ...] = ()
    approval_rules: tuple[ApprovalRulePayload, ...] = ()
    lifecycle: LifecyclePayload | None = None
    webhook: WebhookPayload | None = None
    # 可选顶层节: 平台能力申明(directory/notify); 申明 ≠ 开通。
    capabilities: tuple[str, ...] = ()

    @field_validator("capabilities", mode="before")
    @classmethod
    def normalize_capabilities(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, (list, tuple)):
            message = "capabilities 必须是字符串数组。"
            raise TypeError(message)
        raw_items = cast("Sequence[object]", value)
        normalized: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(_PLATFORM_CAPABILITY_EMPTY_MESSAGE)
            capability = item.strip()
            if capability in seen:
                continue
            seen.add(capability)
            if capability not in CAPABILITY_VALUES:
                logger.warning(
                    "manifest capabilities 含未知平台能力值, 已记录但不拒绝: %s",
                    capability,
                )
            normalized.append(capability)
        return normalized
