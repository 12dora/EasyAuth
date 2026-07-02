from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import JsonResponse
from django.test import RequestFactory, override_settings

from easyauth.accounts.auth import AUTHENTIK_GROUPS_SESSION_KEY, AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_DISABLED, UserMirror
from easyauth.admin_console.request_guards import require_console_actor, require_post
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.ownership import ConsoleActor

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

type JsonObject = dict[str, JsonValue]

pytestmark = pytest.mark.django_db


def test_require_console_actor_returns_401_when_user_is_not_authenticated() -> None:
    request = _request_with_session()
    request.user = AnonymousUser()

    response = require_console_actor(request)

    assert isinstance(response, JsonResponse)
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert _json_object(response)["error"] == {
        "code": ErrorCode.AUTHENTICATION_FAILED,
        "message": "控制台登录已失效。",
        "details": {},
    }


def test_require_console_actor_rejects_active_non_admin_session() -> None:
    _ = UserMirror.objects.create(authentik_user_id="console-user")
    request = _request_with_session(authentik_user_id="console-user")
    request.user = AnonymousUser()

    response = require_console_actor(request)

    assert isinstance(response, JsonResponse)
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert _json_object(response)["error"] == {
        "code": ErrorCode.PERMISSION_DENIED,
        "message": "无权访问控制台。",
        "details": {},
    }


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_require_console_actor_marks_superuser_from_authentik_group_session() -> None:
    _ = UserMirror.objects.create(authentik_user_id="root")
    request = _request_with_session(
        authentik_user_id="root",
        groups=("developers", "easyauth-admins"),
    )
    request.user = AnonymousUser()

    actor = require_console_actor(request)

    assert isinstance(actor, ConsoleActor)
    assert actor == ConsoleActor(user_id="root", is_superuser=True)


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_IDS=("legacy-root",))
def test_require_console_actor_keeps_legacy_superuser_id_compatibility() -> None:
    _ = UserMirror.objects.create(authentik_user_id="legacy-root")
    request = _request_with_session(authentik_user_id="legacy-root")
    request.user = AnonymousUser()

    actor = require_console_actor(request)

    assert isinstance(actor, ConsoleActor)
    assert actor == ConsoleActor(user_id="legacy-root", is_superuser=True)


def test_require_console_actor_clears_session_for_inactive_user_mirror() -> None:
    _ = UserMirror.objects.create(
        authentik_user_id="disabled-user",
        status=USER_STATUS_DISABLED,
    )
    request = _request_with_session(authentik_user_id="disabled-user")
    request.user = AnonymousUser()

    response = require_console_actor(request)

    assert isinstance(response, JsonResponse)
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert AUTHENTIK_SESSION_KEY not in request.session


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


def _request_with_session(
    *,
    authentik_user_id: str = "",
    groups: tuple[str, ...] = (),
) -> HttpRequest:
    request = RequestFactory().get("/console/apps")
    middleware = SessionMiddleware(lambda _request: JsonResponse({}))
    middleware.process_request(request)
    request.session.save()
    if authentik_user_id:
        request.session[AUTHENTIK_SESSION_KEY] = authentik_user_id
    if groups:
        request.session[AUTHENTIK_GROUPS_SESSION_KEY] = list(groups)
    return request
