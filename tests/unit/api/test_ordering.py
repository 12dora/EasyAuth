from __future__ import annotations

from http import HTTPStatus
from json import loads
from typing import TYPE_CHECKING, Final, cast

from django.http import JsonResponse
from django.test import RequestFactory

from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.ordering import parse_ordering, with_tiebreaker

if TYPE_CHECKING:
    from django.http import HttpRequest

ALLOWED: Final[dict[str, str]] = {
    "name": "name",
    "status": "is_active",
    "created_at": "created_at",
}
DEFAULT: Final[tuple[str, ...]] = ("name",)


def test_parse_ordering_absent_keeps_default_and_appends_pk() -> None:
    result = parse_ordering(_request(), ALLOWED, DEFAULT)

    assert result == ("name", "pk")


def test_parse_ordering_empty_string_uses_default() -> None:
    result = parse_ordering(_request(""), ALLOWED, DEFAULT)

    assert result == ("name", "pk")


def test_parse_ordering_does_not_duplicate_existing_id_tiebreaker() -> None:
    result = parse_ordering(_request(), ALLOWED, ("-created_at", "-id"))

    assert result == ("-created_at", "-id")


def test_parse_ordering_maps_public_name_asc_and_desc() -> None:
    ascending = parse_ordering(_request("status"), ALLOWED, DEFAULT)
    descending = parse_ordering(_request("-status"), ALLOWED, DEFAULT)

    assert ascending == ("is_active", "pk")
    assert descending == ("-is_active", "pk")


def test_parse_ordering_unknown_field_returns_400_validation_error() -> None:
    result = parse_ordering(_request("unknown"), ALLOWED, DEFAULT)

    assert isinstance(result, JsonResponse)
    assert result.status_code == HTTPStatus.BAD_REQUEST
    payload = cast("dict[str, JsonValue]", loads(result.content.decode()))
    error = payload["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert error["details"] == {"field": "ordering", "value": "unknown"}
    message = error["message"]
    assert isinstance(message, str)
    assert "name" in message
    assert "status" in message


def test_with_tiebreaker_appends_pk_when_missing() -> None:
    assert with_tiebreaker(("app_key",)) == ("app_key", "pk")
    assert with_tiebreaker(("name", "pk")) == ("name", "pk")
    assert with_tiebreaker(()) == ("pk",)


def _request(ordering: str | None = None) -> HttpRequest:
    factory = RequestFactory()
    if ordering is None:
        return factory.get("/list")
    return factory.get("/list", {"ordering": ordering})
