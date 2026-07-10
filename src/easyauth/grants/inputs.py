from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.applications.models import AuthorizationGroup, Permission


@dataclass(frozen=True, slots=True)
class AuthorizationGroupGrantInput:
    authorization_group: AuthorizationGroup
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class ScopedDirectGrantInput:
    permission: Permission
    scope_key: str
    expires_at: datetime | None
