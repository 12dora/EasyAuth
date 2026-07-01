from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from easyauth.admin_console.catalog_write_common import ResourceIdPayload


class PermissionCreatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    group_id: int | None = Field(default=None, gt=0)
    group_key: str | None = Field(default=None, min_length=1, max_length=128)
    is_active: bool = True
    supported_scopes: list[str] = Field(default_factory=list)
    risk_level: str = "standard"
    deprecated_reason: str | None = None


class PermissionUpdatePayload(ResourceIdPayload):
    key: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    group_id: int | None = Field(default=None, gt=0)
    group_key: str | None = Field(default=None, min_length=1, max_length=128)
    is_active: bool | None = None
    supported_scopes: list[str] | None = None
    risk_level: str | None = None
    deprecated_reason: str | None = None


class PermissionKeyUpdatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    key: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    group_id: int | None = Field(default=None, gt=0)
    group_key: str | None = Field(default=None, min_length=1, max_length=128)
    is_active: bool | None = None
    supported_scopes: list[str] | None = None
    risk_level: str | None = None
    deprecated_reason: str | None = None
