from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from easyauth.api.errors import JsonValue

if TYPE_CHECKING:
    from django.http import QueryDict

type PortalJsonObject = dict[str, JsonValue]

DEFAULT_PAGE: Final = 1
DEFAULT_PAGE_SIZE: Final = 20
MAX_PAGE_SIZE: Final = 100


@dataclass(frozen=True, slots=True)
class PortalPage:
    items: tuple[PortalJsonObject, ...]
    page: int
    page_size: int
    total_items: int
    total_pages: int


@dataclass(frozen=True, slots=True)
class PageRequest:
    page: int
    page_size: int

    @property
    def start(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def stop(self) -> int:
        return self.start + self.page_size


def page_request(query: QueryDict) -> PageRequest:
    return PageRequest(
        page=_positive_integer(query.get("page"), default=DEFAULT_PAGE, maximum=None),
        page_size=_positive_integer(
            query.get("page_size"),
            default=DEFAULT_PAGE_SIZE,
            maximum=MAX_PAGE_SIZE,
        ),
    )


def build_page(
    items: tuple[PortalJsonObject, ...],
    *,
    request: PageRequest,
    total_items: int,
) -> PortalPage:
    return PortalPage(
        items=items,
        page=request.page,
        page_size=request.page_size,
        total_items=total_items,
        total_pages=_total_pages(total_items=total_items, page_size=request.page_size),
    )


def paginate_items(items: tuple[PortalJsonObject, ...], query: QueryDict) -> PortalPage:
    request = page_request(query)
    return build_page(
        items[request.start:request.stop],
        request=request,
        total_items=len(items),
    )


def _positive_integer(value: str | None, *, default: int, maximum: int | None) -> int:
    parsed_value = _integer_or_none(value)
    if parsed_value is None or parsed_value < 1:
        return default
    if maximum is not None and parsed_value > maximum:
        return maximum
    return parsed_value


def _integer_or_none(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _total_pages(*, total_items: int, page_size: int) -> int:
    if total_items == 0:
        return 0
    return ((total_items - 1) // page_size) + 1
