from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.grants.query import PermissionSnapshot

__all__: Final = ("grant_lifecycle_summary",)


def grant_lifecycle_summary(snapshot: PermissionSnapshot) -> tuple[str, datetime | None]:
    expirations = tuple(item.expires_at for item in (*snapshot.groups, *snapshot.grants))
    timed_expirations = tuple(expiration for expiration in expirations if expiration is not None)
    if not timed_expirations:
        return "permanent", None
    if len(timed_expirations) == len(expirations):
        return "timed", min(timed_expirations)
    return "mixed", min(timed_expirations)
