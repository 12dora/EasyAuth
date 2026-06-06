from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class MatrixAssignmentPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    role_id: int = Field(gt=0)
    permission_id: int = Field(gt=0)
    enabled: bool


class MatrixKeyAssignmentPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    role_key: str = Field(min_length=1)
    permission_key: str = Field(min_length=1)


class MatrixSavePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    version: str | None = Field(default=None, min_length=1)
    base_version: str | None = Field(default=None, min_length=1)
    assignments: tuple[MatrixAssignmentPayload, ...] = ()
    add: tuple[MatrixKeyAssignmentPayload, ...] = ()
    remove: tuple[MatrixKeyAssignmentPayload, ...] = ()
