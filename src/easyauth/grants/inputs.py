from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from easyauth.grants.models import MEMBERSHIP_SOURCE_USER

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.applications.models import AuthorizationGroup, Permission


@dataclass(frozen=True, slots=True)
class AuthorizationGroupGrantInput:
    authorization_group: AuthorizationGroup
    expires_at: datetime | None
    source: str = MEMBERSHIP_SOURCE_USER
    department_policy_id: int | None = None


@dataclass(frozen=True, slots=True)
class ScopedDirectGrantInput:
    permission: Permission
    scope_key: str
    expires_at: datetime | None
    source: str = MEMBERSHIP_SOURCE_USER
    department_policy_id: int | None = None
