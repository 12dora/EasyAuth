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
from easyauth.accounts.models import UserMirror
from easyauth.admin_console.app_capability_api import (
    console_app_capabilities,
    console_app_capability_detail,
)
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import (
    CAPABILITY_DIRECTORY,
    CAPABILITY_NOTIFY,
    App,
    AppCapability,
)
from easyauth.audit.models import AuditLog

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

type JsonObject = dict[str, JsonValue]

pytestmark = pytest.mark.django_db


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_list_capabilities_defaults_to_disabled() -> None:
    app = App.objects.create(app_key="cap-api-list", name="Cap API")
    request = _superuser_request("GET", f"/console/api/v1/apps/{app.app_key}/capabilities")

    response = console_app_capabilities(request, app.app_key)

    assert response.status_code == HTTPStatus.OK
    body = _json_object(response)
    assert body["capabilities"] == [
        {
            "capability": CAPABILITY_DIRECTORY,
            "enabled": False,
            "config": {},
            "updated_by": "",
            "updated_at": None,
            "created_at": None,
        },
        {
            "capability": CAPABILITY_NOTIFY,
            "enabled": False,
            "config": {},
            "updated_by": "",
            "updated_at": None,
            "created_at": None,
        },
    ]


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_put_enables_capability_and_writes_audit() -> None:
    app = App.objects.create(app_key="cap-api-enable", name="Cap API")
    request = _superuser_request(
        "PUT",
        f"/console/api/v1/apps/{app.app_key}/capabilities/{CAPABILITY_NOTIFY}",
        body={"enabled": True, "config": {"daily_recipient_quota": 2000}},
        user_id="cap-super",
    )

    response = console_app_capability_detail(request, app.app_key, CAPABILITY_NOTIFY)

    assert response.status_code == HTTPStatus.OK
    body = _json_object(response)
    item = cast("JsonObject", body["capability"])
    assert item["capability"] == CAPABILITY_NOTIFY
    assert item["enabled"] is True
    assert item["config"] == {"daily_recipient_quota": 2000}
    assert item["updated_by"] == "cap-super"

    row = AppCapability.objects.get(app=app, capability=CAPABILITY_NOTIFY)
    assert row.enabled is True
    assert row.config == {"daily_recipient_quota": 2000}

    audit = AuditLog.objects.get(event_type="app_capability_enabled")
    assert audit.actor_id == "cap-super"
    assert audit.target_type == "app"
    assert audit.target_id == str(app.id)
    assert audit.metadata["capability"] == CAPABILITY_NOTIFY
    assert audit.metadata["updated_by"] == "cap-super"


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_put_disables_capability_and_writes_audit() -> None:
    app = App.objects.create(app_key="cap-api-disable", name="Cap API")
    _ = AppCapability.objects.create(
        app=app,
        capability=CAPABILITY_DIRECTORY,
        enabled=True,
        updated_by="previous",
    )
    request = _superuser_request(
        "PUT",
        f"/console/api/v1/apps/{app.app_key}/capabilities/{CAPABILITY_DIRECTORY}",
        body={"enabled": False},
        user_id="cap-super",
    )

    response = console_app_capability_detail(request, app.app_key, CAPABILITY_DIRECTORY)

    assert response.status_code == HTTPStatus.OK
    assert AppCapability.objects.get(app=app, capability=CAPABILITY_DIRECTORY).enabled is False
    audit = AuditLog.objects.get(event_type="app_capability_disabled")
    assert audit.metadata["capability"] == CAPABILITY_DIRECTORY


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_put_without_enabled_change_skips_toggle_audit() -> None:
    app = App.objects.create(app_key="cap-api-config", name="Cap API")
    _ = AppCapability.objects.create(
        app=app,
        capability=CAPABILITY_NOTIFY,
        enabled=True,
        config={"rate_per_minute": 10},
        updated_by="previous",
    )
    request = _superuser_request(
        "PUT",
        f"/console/api/v1/apps/{app.app_key}/capabilities/{CAPABILITY_NOTIFY}",
        body={"enabled": True, "config": {"rate_per_minute": 60}},
        user_id="cap-super",
    )

    response = console_app_capability_detail(request, app.app_key, CAPABILITY_NOTIFY)

    assert response.status_code == HTTPStatus.OK
    row = AppCapability.objects.get(app=app, capability=CAPABILITY_NOTIFY)
    assert row.config == {"rate_per_minute": 60}
    assert not AuditLog.objects.filter(
        event_type__in=("app_capability_enabled", "app_capability_disabled"),
    ).exists()


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_non_superuser_is_forbidden() -> None:
    app = App.objects.create(app_key="cap-api-deny", name="Cap API")
    request = _console_request(
        "GET",
        f"/console/api/v1/apps/{app.app_key}/capabilities",
        user_id="cap-user",
        groups=("developers",),
    )

    response = console_app_capabilities(request, app.app_key)

    assert response.status_code == HTTPStatus.FORBIDDEN
    body = _json_object(response)
    assert body["error"] == {
        "code": ErrorCode.PERMISSION_DENIED,
        "message": "只有系统管理员可以执行该操作。",
        "details": {},
    }


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_unknown_capability_is_rejected() -> None:
    app = App.objects.create(app_key="cap-api-unknown", name="Cap API")
    request = _superuser_request(
        "PUT",
        f"/console/api/v1/apps/{app.app_key}/capabilities/email",
        body={"enabled": True},
    )

    response = console_app_capability_detail(request, app.app_key, "email")

    assert response.status_code == HTTPStatus.BAD_REQUEST
    body = _json_object(response)
    error = cast("JsonObject", body["error"])
    assert error["code"] == ErrorCode.VALIDATION_ERROR


def _superuser_request(
    method: str,
    path: str,
    *,
    body: dict[str, JsonValue] | None = None,
    user_id: str = "cap-super",
) -> HttpRequest:
    return _console_request(
        method,
        path,
        body=body,
        user_id=user_id,
        groups=("easyauth-admins",),
    )


def _console_request(
    method: str,
    path: str,
    *,
    body: dict[str, JsonValue] | None = None,
    user_id: str,
    groups: tuple[str, ...],
) -> HttpRequest:
    _ = UserMirror.objects.get_or_create(authentik_user_id=user_id)
    factory = RequestFactory()
    if method == "GET":
        request = factory.get(path)
    elif method == "PUT":
        request = factory.put(
            path,
            data=json.dumps(body or {}),
            content_type="application/json",
        )
    else:
        message = f"unsupported method: {method}"
        raise AssertionError(message)
    middleware = SessionMiddleware(lambda _request: JsonResponse({}))
    middleware.process_request(request)
    request.session[AUTHENTIK_SESSION_KEY] = user_id
    request.session[AUTHENTIK_GROUPS_SESSION_KEY] = list(groups)
    request.session.save()
    request.user = AnonymousUser()
    return request


def _json_object(response: HttpResponse) -> JsonObject:
    payload: JsonObject = cast("JsonObject", json.loads(response.content.decode()))
    assert isinstance(payload, dict)
    return payload
