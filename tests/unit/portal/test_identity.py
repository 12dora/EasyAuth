from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpRequest, JsonResponse
from django.test import RequestFactory

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import USER_STATUS_DEPARTED, UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.portal.handover_api import portal_user as handover_portal_user
from easyauth.portal.identity import PORTAL_LOGIN_EXPIRED_MESSAGE, portal_user

if TYPE_CHECKING:
    from django.http import HttpResponse

type JsonObject = dict[str, JsonValue]

pytestmark = pytest.mark.django_db


def test_portal_user_returns_active_session_user() -> None:
    user = UserMirror.objects.create(authentik_user_id="portal-active", name="门户用户")
    request = _session_request(user.authentik_user_id)

    result = portal_user(request)

    assert result == user


def test_portal_user_rejects_missing_session() -> None:
    request = _session_request(None)

    result = portal_user(request)

    assert isinstance(result, JsonResponse)
    assert result.status_code == HTTPStatus.UNAUTHORIZED
    assert _error_object(result)["code"] == ErrorCode.AUTHENTICATION_FAILED
    assert _error_object(result)["message"] == PORTAL_LOGIN_EXPIRED_MESSAGE


def test_portal_user_pops_session_when_user_missing() -> None:
    request = _session_request("gone-user")

    result = portal_user(request)

    assert isinstance(result, JsonResponse)
    assert result.status_code == HTTPStatus.UNAUTHORIZED
    assert AUTHENTIK_SESSION_KEY not in request.session


def test_portal_user_rejects_inactive_user() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="portal-departed",
        name="离职",
        status=USER_STATUS_DEPARTED,
    )
    request = _session_request(user.authentik_user_id)

    result = portal_user(request)

    assert isinstance(result, JsonResponse)
    assert result.status_code == HTTPStatus.UNAUTHORIZED
    assert AUTHENTIK_SESSION_KEY not in request.session


def test_handover_portal_user_forbids_local_admin() -> None:
    subject = f"{LOCAL_ADMIN_SUBJECT_PREFIX}root"
    _ = UserMirror.objects.create(authentik_user_id=subject, name="本地管理员")
    request = _session_request(subject)

    result = handover_portal_user(request)

    assert isinstance(result, JsonResponse)
    assert result.status_code == HTTPStatus.FORBIDDEN
    assert _error_object(result)["code"] == ErrorCode.PERMISSION_DENIED


def _session_request(authentik_user_id: str | None) -> HttpRequest:
    request = RequestFactory().get("/portal/api/v1/grants")
    request.session = SessionStore()
    request.session.save()
    if authentik_user_id is not None:
        request.session[AUTHENTIK_SESSION_KEY] = authentik_user_id
    return request


def _error_object(response: HttpResponse) -> JsonObject:
    payload: JsonObject = cast("JsonObject", json.loads(response.content.decode()))
    error = payload["error"]
    assert isinstance(error, dict)
    return cast("JsonObject", error)
