from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from django.contrib.auth.models import AnonymousUser, User
from django.http import JsonResponse
from django.test import RequestFactory

from easyauth.admin_console.request_guards import require_console_actor, require_post
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.ownership import ConsoleActor

if TYPE_CHECKING:
    from django.http import HttpResponse

type JsonObject = dict[str, JsonValue]


def test_require_console_actor_returns_401_when_user_is_not_authenticated() -> None:
    request = RequestFactory().get("/console/apps")
    request.user = AnonymousUser()

    response = require_console_actor(request)

    assert isinstance(response, JsonResponse)
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert _json_object(response)["error"] == {
        "code": ErrorCode.AUTHENTICATION_FAILED,
        "message": "控制台登录已失效。",
        "details": {},
    }


def test_require_console_actor_maps_authenticated_user_to_console_actor() -> None:
    request = RequestFactory().get("/console/apps")
    request.user = User(username="console-user", is_superuser=False)

    actor = require_console_actor(request)

    assert isinstance(actor, ConsoleActor)
    assert actor == ConsoleActor(user_id="console-user", is_superuser=False)


def test_require_console_actor_preserves_superuser_flag() -> None:
    request = RequestFactory().get("/console/apps")
    request.user = User(username="root", is_superuser=True)

    actor = require_console_actor(request)

    assert isinstance(actor, ConsoleActor)
    assert actor == ConsoleActor(user_id="root", is_superuser=True)


def test_require_post_returns_none_for_post_request() -> None:
    request = RequestFactory().post("/console/apps/app-001/query-test")

    assert require_post(request) is None


def test_require_post_returns_405_for_non_post_request() -> None:
    request = RequestFactory().get("/console/apps/app-001/query-test")

    response = require_post(request)

    assert response is not None
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert _json_object(response)["error"] == {
        "code": ErrorCode.VALIDATION_ERROR,
        "message": "请求方法无效。",
        "details": {},
    }


def _json_object(response: HttpResponse) -> JsonObject:
    payload: JsonObject = cast("JsonObject", json.loads(response.content.decode()))
    assert isinstance(payload, dict)
    return payload
