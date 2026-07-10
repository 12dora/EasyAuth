from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, override

from django.db import models
from django.utils.dateparse import parse_datetime

from easyauth.admin_console.api_responses import error_response
from easyauth.api.errors import ErrorCode
from easyauth.api.pagination import total_pages
from easyauth.grants.models import GRANT_STATUS_REVOKED

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import JsonResponse, QueryDict

    from easyauth.access_requests.models import AccessRequest
    from easyauth.audit.models import AuditLog
    from easyauth.grants.models import AccessGrant

DEFAULT_PAGE: Final = 1
DEFAULT_PAGE_SIZE: Final = 20
MAX_PAGE_SIZE: Final = 100
MAX_PAGE: Final = 100_000
MAX_POSITIVE_INTEGER: Final = 2_147_483_647


@dataclass(frozen=True, slots=True)
class OperationFilterValidationError(ValueError):
    key: str
    value: str
    message: str

    @override
    def __str__(self) -> str:
        return self.message


def operation_filter_error_response(error: OperationFilterValidationError) -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        error.message,
        {"field": error.key, "value": error.value},
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
    )


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
    queryset = _filter_item_expiration(queryset, query)
    return _filter_revoked(queryset, query)


def filter_audit_logs(queryset: QuerySet[AuditLog], query: QueryDict) -> QuerySet[AuditLog]:
    queryset = _filter_text(queryset, query, key="app_key", lookup="metadata__app_key")
    queryset = _filter_text(queryset, query, key="event_type", lookup="event_type")
    queryset = _filter_text(queryset, query, key="actor_id", lookup="actor_id")
    queryset = _filter_text(queryset, query, key="target_id", lookup="target_id")
    queryset = _filter_datetime(queryset, query, key="created_from", lookup="created_at__gte")
    return _filter_datetime(queryset, query, key="created_to", lookup="created_at__lte")


def paginate_queryset[T: models.Model](queryset: QuerySet[T], query: QueryDict) -> Page[T]:
    page = _positive_integer(
        query.get("page"),
        key="page",
        default=DEFAULT_PAGE,
        maximum=MAX_PAGE,
    )
    page_size = _positive_integer(
        query.get("page_size"),
        key="page_size",
        default=DEFAULT_PAGE_SIZE,
        maximum=MAX_PAGE_SIZE,
    )
    total_items = queryset.count()
    start = (page - 1) * page_size
    stop = start + page_size
    return Page(
        items=tuple(queryset[start:stop]),
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages(total_items=total_items, page_size=page_size),
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
    value = _integer_or_none(query.get(key), key=key)
    if value is None:
        return queryset
    if value < 1 or value > MAX_POSITIVE_INTEGER:
        raise OperationFilterValidationError(
            key=key,
            value=str(value),
            message=f"{key} 必须为 1 至 {MAX_POSITIVE_INTEGER} 之间的整数。",
        )
    return queryset.filter(**{lookup: value})


def _filter_boolean[T: models.Model](
    queryset: QuerySet[T],
    query: QueryDict,
    *,
    key: str,
    lookup: str,
) -> QuerySet[T]:
    value = _boolean_or_none(query.get(key), key=key)
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
        raise OperationFilterValidationError(
            key=key,
            value=raw_value,
            message=f"{key} 必须为 ISO 8601 datetime。",
        )
    return queryset.filter(**{lookup: value})


def _filter_revoked(queryset: QuerySet[AccessGrant], query: QueryDict) -> QuerySet[AccessGrant]:
    value = _boolean_or_none(query.get("revoked"), key="revoked")
    if value is None:
        return queryset
    if value:
        return queryset.filter(status=GRANT_STATUS_REVOKED)
    return queryset.exclude(status=GRANT_STATUS_REVOKED)


def _filter_item_expiration(
    queryset: QuerySet[AccessGrant],
    query: QueryDict,
) -> QuerySet[AccessGrant]:
    raw_value = query.get("expires_before", "")
    if raw_value == "":
        return queryset
    value = parse_datetime(raw_value)
    if value is None:
        raise OperationFilterValidationError(
            key="expires_before",
            value=raw_value,
            message="expires_before 必须为 ISO 8601 datetime。",
        )
    return queryset.filter(
        models.Q(grant_groups__expires_at__lte=value)
        | models.Q(grant_permissions__expires_at__lte=value),
    ).distinct()


def _positive_integer(
    value: str | None,
    *,
    key: str,
    default: int,
    maximum: int | None,
) -> int:
    parsed_value = _integer_or_none(value, key=key)
    if parsed_value is None:
        return default
    if parsed_value < 1:
        raise OperationFilterValidationError(
            key=key,
            value=value or "",
            message=f"{key} 必须为正整数。",
        )
    if maximum is not None and parsed_value > maximum:
        raise OperationFilterValidationError(
            key=key,
            value=value or "",
            message=f"{key} 不得大于 {maximum}。",
        )
    return parsed_value


def _integer_or_none(value: str | None, *, key: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise OperationFilterValidationError(
            key=key,
            value=value,
            message=f"{key} 必须为整数。",
        ) from exc


def _boolean_or_none(value: str | None, *, key: str) -> bool | None:
    match value:
        case "true":
            return True
        case "false":
            return False
        case None | "":
            return None
        case _:
            raise OperationFilterValidationError(
                key=key,
                value=value,
                message=f"{key} 必须为 true 或 false。",
            )
