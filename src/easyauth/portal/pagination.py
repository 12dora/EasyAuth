from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, override

from easyauth.api.errors import JsonValue
from easyauth.api.pagination import total_pages

if TYPE_CHECKING:
    from django.http import QueryDict

type PortalJsonObject = dict[str, JsonValue]

DEFAULT_PAGE: Final = 1
DEFAULT_PAGE_SIZE: Final = 20
MAX_PAGE_SIZE: Final = 100
# page 上界: 防止任意大 page 在 DB 分页端点产生巨大 OFFSET。
MAX_PAGE: Final = 100_000
ERROR_POSITIVE_INTEGER: Final = "positive_integer"
ERROR_MAXIMUM: Final = "maximum"
ERROR_INTEGER: Final = "integer"


@dataclass(frozen=True, slots=True)
class PortalPaginationValidationError(ValueError):
    key: str
    kind: str
    maximum: int | None = None

    @override
    def __str__(self) -> str:
        match self.kind:
            case "positive_integer":
                return f"{self.key} 必须为正整数。"
            case "maximum":
                return f"{self.key} 不得大于 {self.maximum}。"
            case _:
                return f"{self.key} 必须为整数。"


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
        page=_positive_integer(
            query.get("page"),
            key="page",
            default=DEFAULT_PAGE,
            maximum=MAX_PAGE,
        ),
        page_size=_positive_integer(
            query.get("page_size"),
            key="page_size",
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
        total_pages=total_pages(total_items=total_items, page_size=request.page_size),
    )


def _positive_integer(value: str | None, *, key: str, default: int, maximum: int | None) -> int:
    parsed_value = _integer_or_none(value, key=key)
    if parsed_value is None:
        return default
    if parsed_value < 1:
        raise PortalPaginationValidationError(key=key, kind=ERROR_POSITIVE_INTEGER)
    if maximum is not None and parsed_value > maximum:
        raise PortalPaginationValidationError(
            key=key,
            kind=ERROR_MAXIMUM,
            maximum=maximum,
        )
    return parsed_value


def _integer_or_none(value: str | None, *, key: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise PortalPaginationValidationError(key=key, kind=ERROR_INTEGER) from exc
