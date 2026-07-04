from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from easyauth.applications.models import Permission


@dataclass(frozen=True, slots=True)
class ScopedDirectGrantInput:
    permission: Permission
    scope_key: str
