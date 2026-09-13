from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from django.db import models
from django.db.models.expressions import F, OrderBy
from django.db.models.functions import NullIf
from django.http import JsonResponse

from easyauth.api.errors import ErrorCode
from easyauth.api.responses import error_response

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from typing import Protocol

    from django.db.models.expressions import Combinable, Expression
    from django.http import HttpRequest

    class _ResolvedOrderField(Protocol):
        @property
        def output_field(self) -> object: ...

ORDERING_PARAM = "ordering"
TIEBREAKER = "pk"
_TIEBREAKER_FIELDS = frozenset({"pk", "id"})


def parse_ordering(
    request: HttpRequest,
    allowed: Mapping[str, str | tuple[str, ...]],
    default: tuple[str, ...],
) -> tuple[str, ...] | JsonResponse:
    """解析单字段 `ordering` 查询参数。

    允许 `field` 或 `-field`; 未知字段返回 400 VALIDATION_ERROR。
    省略或空值时沿用 `default`, 并在末尾补上稳定并列键 `pk`(若尚无 pk/id)。
    """
    raw = request.GET.get(ORDERING_PARAM)
    if raw is None or raw.strip() == "":
        return with_tiebreaker(default)
    return _parse_ordering_field(raw.strip(), allowed)


def with_tiebreaker(order: tuple[str, ...]) -> tuple[str, ...]:
    """确保排序表达式以 pk/id 收尾, 分页结果跨页稳定。"""
    if not order:
        return (TIEBREAKER,)
    last = order[-1].lstrip("-")
    if last in _TIEBREAKER_FIELDS:
        return order
    return (*order, TIEBREAKER)


def _parse_ordering_field(
    raw: str,
    allowed: Mapping[str, str | tuple[str, ...]],
) -> tuple[str, ...] | JsonResponse:
    descending = raw.startswith("-")
    field = raw[1:] if descending else raw
    expression = allowed.get(field)
    if expression is None:
        return _invalid_ordering_response(raw, allowed)
    fields = (expression,) if isinstance(expression, str) else expression
    return with_tiebreaker(tuple(f"-{field}" if descending else field for field in fields))


def _invalid_ordering_response(
    raw: str, allowed: Mapping[str, str | tuple[str, ...]]
) -> JsonResponse:
    fields = ", ".join(sorted(allowed))
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        f"ordering 必须为以下字段之一: {fields}。",
        {"field": ORDERING_PARAM, "value": raw},
        status=HTTPStatus.BAD_REQUEST,
    )


def apply_ordering[QS: models.QuerySet[models.Model]](
    request: HttpRequest,
    queryset: QS,
    allowed: Mapping[str, str | tuple[str, ...]],
    default: tuple[str, ...],
    *,
    annotations: Mapping[str, Callable[[], Combinable]] | None = None,
) -> QS | JsonResponse:
    """统一校验并在分页前排序; 仅构建当前排序所需注解, 升序空值置后。"""
    ordering = parse_ordering(request, allowed, default)
    if isinstance(ordering, JsonResponse):
        return ordering
    for field in ordering:
        name = field.lstrip("-")
        if annotations is not None and name in annotations:
            queryset = queryset.annotate(**{name: annotations[name]()})
    expressions: list[OrderBy] = [_nulls_last_order(queryset, field) for field in ordering]
    return queryset.order_by(*expressions)


def _nulls_last_order(queryset: models.QuerySet[models.Model], field: str) -> OrderBy:
    name = field.lstrip("-")
    expression: F | NullIf = F(name)
    if _has_text_output(queryset.query.resolve_ref(name)):
        expression = NullIf(expression, models.Value(""))
    if field.startswith("-"):
        return expression.desc(nulls_last=True)
    return expression.asc(nulls_last=True)


def _has_text_output(resolved: Expression) -> bool:
    # django-stubs 将 Expression.output_field 标为未参数化 Field; 经 Protocol 收成 object。
    typed = cast("_ResolvedOrderField", resolved)
    return isinstance(typed.output_field, (models.CharField, models.TextField))
