from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from easyauth.api.errors import ErrorCode
from easyauth.api.responses import error_response

if TYPE_CHECKING:
    from collections.abc import Mapping

    from django.http import HttpRequest, JsonResponse

ORDERING_PARAM = "ordering"
TIEBREAKER = "pk"
_TIEBREAKER_FIELDS = frozenset({"pk", "id"})


def parse_ordering(
    request: HttpRequest,
    allowed: Mapping[str, str],
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
    allowed: Mapping[str, str],
) -> tuple[str, ...] | JsonResponse:
    descending = raw.startswith("-")
    field = raw[1:] if descending else raw
    expression = allowed.get(field)
    if expression is None:
        return _invalid_ordering_response(raw, allowed)
    ordered = f"-{expression}" if descending else expression
    return with_tiebreaker((ordered,))


def _invalid_ordering_response(raw: str, allowed: Mapping[str, str]) -> JsonResponse:
    fields = ", ".join(sorted(allowed))
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        f"ordering 必须为以下字段之一: {fields}。",
        {"field": ORDERING_PARAM, "value": raw},
        status=HTTPStatus.BAD_REQUEST,
    )
