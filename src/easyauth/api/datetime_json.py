from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


def datetime_value(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
