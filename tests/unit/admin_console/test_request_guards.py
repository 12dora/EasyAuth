from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import JsonResponse
from django.test import RequestFactory, override_settings

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
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


def test_require_console_actor_maps_active_authentik_session_to_console_actor() -> None:
    _ = UserMirror.objects.create(authentik_user_id="console-user")
    request = _request_with_session(authentik_user_id="console-user")
    request.user = AnonymousUser()

    actor = require_console_actor(request)

    assert isinstance(actor, ConsoleActor)
    assert actor == ConsoleActor(user_id="console-user", is_superuser=False)


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_require_console_actor_marks_superuser_from_authentik_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = UserMirror.objects.create(authentik_user_id="root")
    _patch_authentik_groups(monkeypatch, ("developers", "easyauth-admins"))
    request = _request_with_session(authentik_user_id="root")
    request.user = AnonymousUser()

    actor = require_console_actor(request)

    assert isinstance(actor, ConsoleActor)
    assert actor == ConsoleActor(user_id="root", is_superuser=True)


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_require_console_actor_revokes_superuser_when_authentik_removes_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = UserMirror.objects.create(authentik_user_id="root")
    _patch_authentik_groups(monkeypatch, ())
    request = _request_with_session(authentik_user_id="root")
    request.user = AnonymousUser()

    actor = require_console_actor(request)

    assert isinstance(actor, ConsoleActor)
    assert actor == ConsoleActor(user_id="root", is_superuser=False)


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
) -> HttpRequest:
    request = RequestFactory().get("/console/apps")
    middleware = SessionMiddleware(lambda _request: JsonResponse({}))
    middleware.process_request(request)
    request.session.save()
    if authentik_user_id:
        request.session[AUTHENTIK_SESSION_KEY] = authentik_user_id
    return request


def _patch_authentik_groups(
    monkeypatch: pytest.MonkeyPatch,
    groups: tuple[str, ...],
) -> None:
    class FakeAuthentikClient:
        def user_group_names_by_uid(self, authentik_user_uid: str) -> tuple[str, ...]:
            assert authentik_user_uid == "root"
            return groups

    monkeypatch.setattr(
        "easyauth.admin_console.identity.AuthentikAdminClient.from_settings",
        lambda: FakeAuthentikClient(),
    )
