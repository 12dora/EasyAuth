from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from easyauth.applications.models import Permission


class ManagedScopePolicyPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    mode: str = Field(default="inherit", min_length=1, max_length=64)
    resolver: str = Field(default="", max_length=64)
    enabled: bool = True


class AuthorizationGroupGrantPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    permission: str = Field(min_length=1, max_length=128)
    scope: str = Field(min_length=1, max_length=64)
    is_active: bool = True
    managed_scope_policy: ManagedScopePolicyPayload | None = None


class AuthorizationGroupPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    key: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    name_en: str = Field(default="", max_length=128)
    description: str = ""
    description_en: str = ""
    requestable: bool = True
    is_active: bool = True
    grants: tuple[AuthorizationGroupGrantPayload, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedAuthorizationGroupGrant:
    permission: Permission
    scope_key: str
    is_active: bool
    managed_scope_policy: ManagedScopePolicyPayload | None


@dataclass(frozen=True, slots=True)
class AuthorizationGroupQueryOptions:
    include_inactive: bool
    status: str
