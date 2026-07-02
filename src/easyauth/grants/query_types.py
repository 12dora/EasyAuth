from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResolvedManagedUsers:
    user_ids: tuple[str, ...]
    resolver: str
    resolved_at: str
