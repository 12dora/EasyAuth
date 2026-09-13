from __future__ import annotations

from typing import TYPE_CHECKING, overload

if TYPE_CHECKING:
    from datetime import datetime


@overload
def datetime_value(value: None) -> None: ...
@overload
def datetime_value(value: datetime) -> str: ...
def datetime_value(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
