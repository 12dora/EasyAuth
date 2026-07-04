from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue


class Pagination(Protocol):
    """任意具备标准分页字段的对象 (Page[T], PortalPage 等)。"""

    page: int
    page_size: int
    total_items: int
    total_pages: int


def pagination_item(page: Pagination) -> dict[str, JsonValue]:
    return {
        "page": page.page,
        "page_size": page.page_size,
        "total_items": page.total_items,
        "total_pages": page.total_pages,
    }


def total_pages(*, total_items: int, page_size: int) -> int:
    if total_items == 0:
        return 0
    return ((total_items - 1) // page_size) + 1
