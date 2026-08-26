from __future__ import annotations

import re
from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 控制台应用写入契约: app_key 格式、名称非空、成员 user_id 去空白去重。
APP_KEY_INVALID_MESSAGE: Final = "app_key 格式无效。"
APP_KEY_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
NAME_BLANK_MESSAGE: Final = "name 不能为空。"
CONFIGURATION_ISSUE_TARGET_TYPES: Final = {
    "app_inactive": "app",
    "active_credential_missing": "credential",
    "active_permission_missing": "permission",
    "active_authorization_group_missing": "authorization_group",
    "active_owner_missing": "membership",
    "requestable_authorization_group_approval_rule_missing": "authorization_group",
    "authorization_group_grant_target_inactive": "authorization_group_grant",
    "managed_scope_app_default_policy_missing": "authorization_group_grant",
    "managed_scope_grant_policy_missing": "authorization_group_grant",
    "managed_scope_policy_disabled": "authorization_group_grant",
    "permission_supported_scopes_missing": "permission",
    "permission_group_inactive": "permission_group",
}


class AppCreatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    app_key: str = Field(max_length=64)
    name: str = Field(max_length=128)
    description: str = ""
    is_active: bool = True
    owner_user_ids: list[str] = Field(default_factory=list)
    developer_user_ids: list[str] = Field(default_factory=list)

    @field_validator("app_key")
    @classmethod
    def validate_app_key(cls, value: str) -> str:
        normalized = value.strip()
        if APP_KEY_PATTERN.fullmatch(normalized) is None:
            raise ValueError(APP_KEY_INVALID_MESSAGE)
        return normalized

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError(NAME_BLANK_MESSAGE)
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("owner_user_ids", "developer_user_ids")
    @classmethod
    def normalize_user_ids(cls, value: list[str]) -> list[str]:
        return _normalize_user_ids(value)


class AppPatchPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    name: str | None = Field(default=None, max_length=128)
    description: str | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized == "":
            raise ValueError(NAME_BLANK_MESSAGE)
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


def _normalize_user_ids(user_ids: list[str]) -> list[str]:
    normalized_ids: list[str] = []
    seen: set[str] = set()
    for user_id in user_ids:
        normalized = user_id.strip()
        if normalized == "" or normalized in seen:
            continue
        seen.add(normalized)
        normalized_ids.append(normalized)
    return normalized_ids
