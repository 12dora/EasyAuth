from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.api.pagination import paginated_list_payload

if TYPE_CHECKING:
    from collections.abc import Sequence

    from easyauth.api.errors import JsonValue

__all__ = ["list_payload", "paginated_list_payload"]


def list_payload(items: Sequence[JsonValue]) -> dict[str, JsonValue]:
    return {"data": list(items)}
