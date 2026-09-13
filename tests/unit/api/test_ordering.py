from __future__ import annotations

import importlib
from http import HTTPStatus
from json import loads
from typing import TYPE_CHECKING, Final, cast

import pytest
from django.db.models import Value
from django.http import JsonResponse
from django.test import RequestFactory

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.ordering import apply_ordering, parse_ordering, with_tiebreaker

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


@pytest.mark.django_db
def test_apply_ordering_adds_requested_annotation_and_places_empty_last() -> None:
    UserMirror.objects.create(authentik_user_id="u1", name="")
    UserMirror.objects.create(authentik_user_id="u2", name="乙")
    UserMirror.objects.create(authentik_user_id="u3", name="甲")
    request = _request("name")
    result = apply_ordering(
        request,
        UserMirror.objects.all(),
        {"name": "name", "computed": "computed"},
        ("name",),
        annotations={"computed": lambda: Value("x")},
    )
    assert list(result.values_list("name", flat=True))[-1] == ""
    assert set(result.values_list("name", flat=True)[:2]) == {"甲", "乙"}
    assert "computed" not in result.query.annotations


@pytest.mark.parametrize(
    ("module_name", "constant_name"),
    [
        ("easyauth.portal.api_data", "PORTAL_GRANT_ORDERING"),
        ("easyauth.portal.access_request_data", "PORTAL_ACCESS_REQUEST_ORDERING"),
        ("easyauth.portal.approvals_api", "PORTAL_APPROVAL_ORDERING"),
        ("easyauth.admin_console.apps_api_reads", "CONSOLE_APP_ORDERING"),
        ("easyauth.admin_console.teams_api", "TEAM_LIST_ORDERING"),
        ("easyauth.admin_console.users_api", "PEOPLE_LIST_ORDERING"),
        ("easyauth.admin_console.lifecycle_task_api", "HANDOVER_TASK_ORDERING"),
        ("easyauth.admin_console.approval_instances_api", "APPROVAL_INSTANCE_ORDERING"),
        ("easyauth.admin_console.permission_template_api", "TEMPLATE_VERSION_ORDERING"),
        ("easyauth.admin_console.connectors_api_reads", "SYNC_RUN_ORDERING"),
        ("easyauth.admin_console.operations_api", "ACCESS_REQUEST_ORDERING"),
        ("easyauth.admin_console.operations_api", "ACCESS_GRANT_ORDERING"),
        ("easyauth.admin_console.audit_api", "AUDIT_LOG_ORDERING"),
    ],
)
def test_every_endpoint_ordering_key_accepts_both_directions(
    module_name: str,
    constant_name: str,
) -> None:
    module = importlib.import_module(module_name)
    allowed = getattr(module, constant_name)
    for field in allowed:
        ascending = parse_ordering(_request(field), allowed, (field,))
        assert isinstance(ascending, tuple)
        assert ascending[-1] in {"pk", "id"}
        descending = parse_ordering(_request(f"-{field}"), allowed, (field,))
        assert isinstance(descending, tuple)
        assert descending[0].startswith("-")


def test_new_operations_and_audit_ordering_reject_unknown_values() -> None:
    for module_name, constant_name in (
        ("easyauth.admin_console.operations_api", "ACCESS_REQUEST_ORDERING"),
        ("easyauth.admin_console.operations_api", "ACCESS_GRANT_ORDERING"),
        ("easyauth.admin_console.audit_api", "AUDIT_LOG_ORDERING"),
    ):
        allowed = getattr(importlib.import_module(module_name), constant_name)
        response = parse_ordering(_request("does_not_exist"), allowed, ("id",))
        assert isinstance(response, JsonResponse)
        assert response.status_code == HTTPStatus.BAD_REQUEST
