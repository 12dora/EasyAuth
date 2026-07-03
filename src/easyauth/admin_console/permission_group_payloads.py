from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from easyauth.admin_console.catalog_write_common import ResourceIdPayload


class PermissionGroupCreatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    name_en: str = Field(default="", max_length=128)
    description: str = ""
    description_en: str = ""
    parent_id: int | None = Field(default=None, gt=0)
    parent_key: str | None = Field(default=None, min_length=1, max_length=128)
    display_order: int = 0
    is_active: bool = True


class PermissionGroupUpdatePayload(ResourceIdPayload):
    key: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    name_en: str | None = Field(default=None, max_length=128)
    description: str | None = None
    description_en: str | None = None
    parent_id: int | None = Field(default=None, gt=0)
    parent_key: str | None = Field(default=None, min_length=1, max_length=128)
    display_order: int | None = None
    is_active: bool | None = None


class PermissionGroupKeyUpdatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    key: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    name_en: str | None = Field(default=None, max_length=128)
    description: str | None = None
    description_en: str | None = None
    parent_id: int | None = Field(default=None, gt=0)
    parent_key: str | None = Field(default=None, min_length=1, max_length=128)
    display_order: int | None = None
    is_active: bool | None = None
