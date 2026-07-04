from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class MatrixKeyAssignmentPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    role_key: str = Field(min_length=1)
    permission_key: str = Field(min_length=1)


class MatrixSavePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    base_version: str | None = Field(default=None, min_length=1)
    add: tuple[MatrixKeyAssignmentPayload, ...] = ()
    remove: tuple[MatrixKeyAssignmentPayload, ...] = ()
