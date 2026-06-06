from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from easyauth.api.errors import JsonValue


def list_payload(items: Sequence[JsonValue]) -> dict[str, JsonValue]:
    data = list(items)
    return {"items": data, "data": data}


def paginated_list_payload(
    *,
    items: Sequence[JsonValue],
    pagination: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    data = list(items)
    return {"items": data, "data": data, "pagination": pagination}
