from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from django.db import models
from django.utils.dateparse import parse_datetime

from easyauth.grants.models import GRANT_STATUS_REVOKED

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import QueryDict

    from easyauth.access_requests.models import AccessRequest
    from easyauth.audit.models import AuditLog
    from easyauth.grants.models import AccessGrant

DEFAULT_PAGE: Final = 1
DEFAULT_PAGE_SIZE: Final = 20
MAX_PAGE_SIZE: Final = 100


@dataclass(frozen=True, slots=True)
class Page[T: models.Model]:
    items: tuple[T, ...]
    page: int
    page_size: int
    total_items: int
    total_pages: int


def filter_access_requests(
    queryset: QuerySet[AccessRequest],
    query: QueryDict,
) -> QuerySet[AccessRequest]:
    queryset = _filter_text(queryset, query, key="app_key", lookup="app__app_key")
    queryset = _filter_text(queryset, query, key="status", lookup="status")
    queryset = _filter_text(queryset, query, key="user_id", lookup="user__authentik_user_id")
    queryset = _filter_text(queryset, query, key="request_type", lookup="request_type")
    queryset = _filter_datetime(queryset, query, key="created_from", lookup="submitted_at__gte")
    queryset = _filter_datetime(queryset, query, key="created_to", lookup="submitted_at__lte")
    queryset = _filter_datetime(queryset, query, key="applied_from", lookup="applied_at__gte")
    queryset = _filter_datetime(queryset, query, key="applied_to", lookup="applied_at__lte")
    return _filter_datetime(queryset, query, key="expires_before", lookup="grant_expires_at__lte")


def filter_access_grants(
    queryset: QuerySet[AccessGrant],
    query: QueryDict,
) -> QuerySet[AccessGrant]:
    queryset = _filter_text(queryset, query, key="app_key", lookup="app__app_key")
    queryset = _filter_text(queryset, query, key="status", lookup="status")
    queryset = _filter_text(queryset, query, key="user_id", lookup="user__authentik_user_id")
    queryset = _filter_integer(queryset, query, key="version", lookup="version")
    queryset = _filter_boolean(queryset, query, key="current", lookup="is_current")
    queryset = _filter_datetime(queryset, query, key="created_from", lookup="created_at__gte")
    queryset = _filter_datetime(queryset, query, key="created_to", lookup="created_at__lte")
    queryset = _filter_datetime(queryset, query, key="updated_from", lookup="updated_at__gte")
    queryset = _filter_datetime(queryset, query, key="updated_to", lookup="updated_at__lte")
    queryset = _filter_datetime(
        queryset,
        query,
        key="expires_before",
        lookup="grant_expires_at__lte",
    )
    return _filter_revoked(queryset, query)


def filter_audit_logs(queryset: QuerySet[AuditLog], query: QueryDict) -> QuerySet[AuditLog]:
    queryset = _filter_text(queryset, query, key="app_key", lookup="metadata__app_key")
    queryset = _filter_text(queryset, query, key="event_type", lookup="event_type")
    queryset = _filter_text(queryset, query, key="actor_id", lookup="actor_id")
    queryset = _filter_text(queryset, query, key="target_id", lookup="target_id")
    queryset = _filter_datetime(queryset, query, key="created_from", lookup="created_at__gte")
    return _filter_datetime(queryset, query, key="created_to", lookup="created_at__lte")


def paginate_queryset[T: models.Model](queryset: QuerySet[T], query: QueryDict) -> Page[T]:
    page = _positive_integer(query.get("page"), default=DEFAULT_PAGE, maximum=None)
    page_size = _positive_integer(
        query.get("page_size"),
        default=DEFAULT_PAGE_SIZE,
        maximum=MAX_PAGE_SIZE,
    )
    total_items = queryset.count()
    start = (page - 1) * page_size
    stop = start + page_size
    total_pages = _total_pages(total_items=total_items, page_size=page_size)
    return Page(
        items=tuple(queryset[start:stop]),
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages,
    )


def _filter_text[T: models.Model](
    queryset: QuerySet[T],
    query: QueryDict,
    *,
    key: str,
    lookup: str,
) -> QuerySet[T]:
    value = query.get(key, "")
    if value == "":
        return queryset
    return queryset.filter(**{lookup: value})


def _filter_integer[T: models.Model](
    queryset: QuerySet[T],
    query: QueryDict,
    *,
    key: str,
    lookup: str,
) -> QuerySet[T]:
    value = _integer_or_none(query.get(key))
    if value is None:
        return queryset
    return queryset.filter(**{lookup: value})


def _filter_boolean[T: models.Model](
    queryset: QuerySet[T],
    query: QueryDict,
    *,
    key: str,
    lookup: str,
) -> QuerySet[T]:
    value = _boolean_or_none(query.get(key))
    if value is None:
        return queryset
    return queryset.filter(**{lookup: value})


def _filter_datetime[T: models.Model](
    queryset: QuerySet[T],
    query: QueryDict,
    *,
    key: str,
    lookup: str,
) -> QuerySet[T]:
    raw_value = query.get(key, "")
    if raw_value == "":
        return queryset
    value = parse_datetime(raw_value)
    if value is None:
        return queryset
    return queryset.filter(**{lookup: value})


def _filter_revoked(queryset: QuerySet[AccessGrant], query: QueryDict) -> QuerySet[AccessGrant]:
    value = _boolean_or_none(query.get("revoked"))
    if value is None:
        return queryset
    if value:
        return queryset.filter(status=GRANT_STATUS_REVOKED)
    return queryset.exclude(status=GRANT_STATUS_REVOKED)


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


def _boolean_or_none(value: str | None) -> bool | None:
    match value:
        case "true" | "1" | "yes":
            return True
        case "false" | "0" | "no":
            return False
        case None | "":
            return None
        case _:
            return None


def _total_pages(*, total_items: int, page_size: int) -> int:
    if total_items == 0:
        return 0
    return ((total_items - 1) // page_size) + 1
