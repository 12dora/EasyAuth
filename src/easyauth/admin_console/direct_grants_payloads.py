from __future__ import annotations

from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from easyauth.admin_console.grant_write_common import AdminGrantWritePayload

IDENTITY_XOR_CODE = "identity_xor"
IDENTITY_XOR_MESSAGE = "必须且只能指定 user_id 或 directory_user 其中一项。"


class DirectoryUserRef(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    source_slug: str = Field(min_length=1, max_length=128)
    corp_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)


class DirectGrantRequestPayload(AdminGrantWritePayload):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    user_id: str | None = Field(default=None, min_length=1, max_length=128)
    directory_user: DirectoryUserRef | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        has_user = self.user_id is not None
        has_directory = self.directory_user is not None
        if has_user == has_directory:
            raise PydanticCustomError(IDENTITY_XOR_CODE, IDENTITY_XOR_MESSAGE)
        return self
