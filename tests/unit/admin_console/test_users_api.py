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
from easyauth.accounts.models import UserMirror
from easyauth.admin_console import identity
from easyauth.admin_console.users_api import (
    CONSOLE_ADMIN_UPDATED_ACTION,
    SELF_REVOKE_ADMIN_MESSAGE,
    _person_item,
    _user_item,
    console_user_console_admin,
)
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.audit.models import AuditLog

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

type JsonObject = dict[str, JsonValue]

pytestmark = pytest.mark.django_db

_AUTHORITY_GROUPS_BY_UID: dict[str, tuple[str, ...]] = {}


class _FakeAuthentikAuthority:
    def user_group_names_by_uid(self, authentik_user_uid: str) -> tuple[str, ...]:
        return _AUTHORITY_GROUPS_BY_UID.get(authentik_user_uid, ())


def test_person_item_includes_console_admin_flag() -> None:
    ordinary = UserMirror.objects.create(
        authentik_user_id="person-flag-ordinary",
        name="普通员工",
        email="ordinary@example.com",
        department="销售部",
    )
    admin = UserMirror.objects.create(
        authentik_user_id="person-flag-admin",
        name="控制台管理员",
        is_console_admin=True,
    )

    ordinary_item = _person_item(ordinary)
    admin_item = _person_item(admin)

    assert ordinary_item["is_console_admin"] is False
    assert admin_item["is_console_admin"] is True
    assert "is_console_admin" not in _user_item(ordinary)


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_put_console_admin_flips_flag_and_is_idempotent() -> None:
    target = UserMirror.objects.create(
        authentik_user_id="people-target",
        name="目标员工",
        email="target@example.com",
        department="研发部",
    )

    granted = console_user_console_admin(
        _superuser_request(
            "PUT",
            f"/console/api/v1/users/{target.authentik_user_id}/console-admin",
            body={"is_console_admin": True},
            user_id="people-super",
        ),
        target.authentik_user_id,
    )
    target.refresh_from_db()
    assert granted.status_code == HTTPStatus.OK
    assert target.is_console_admin is True
    assert _json_object(granted)["user"] == _person_item(target)

    granted_again = console_user_console_admin(
        _superuser_request(
            "PUT",
            f"/console/api/v1/users/{target.authentik_user_id}/console-admin",
            body={"is_console_admin": True},
            user_id="people-super",
        ),
        target.authentik_user_id,
    )
    assert granted_again.status_code == HTTPStatus.OK
    assert _json_object(granted_again)["user"] == _person_item(target)

    revoked = console_user_console_admin(
        _superuser_request(
            "PUT",
            f"/console/api/v1/users/{target.authentik_user_id}/console-admin",
            body={"is_console_admin": False},
            user_id="people-super",
        ),
        target.authentik_user_id,
    )
    target.refresh_from_db()
    assert revoked.status_code == HTTPStatus.OK
    assert target.is_console_admin is False
    assert _json_object(revoked)["user"] == _person_item(target)

    revoked_again = console_user_console_admin(
        _superuser_request(
            "PUT",
            f"/console/api/v1/users/{target.authentik_user_id}/console-admin",
            body={"is_console_admin": False},
            user_id="people-super",
        ),
        target.authentik_user_id,
    )
    assert revoked_again.status_code == HTTPStatus.OK
    assert _json_object(revoked_again)["user"] == _person_item(target)
    assert AuditLog.objects.filter(event_type=CONSOLE_ADMIN_UPDATED_ACTION).count() == 2


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_put_console_admin_forbidden_for_non_superuser() -> None:
    target = UserMirror.objects.create(authentik_user_id="people-deny-target")
    request = _console_request(
        "PUT",
        f"/console/api/v1/users/{target.authentik_user_id}/console-admin",
        body={"is_console_admin": True},
        user_id="people-ordinary",
        groups=(),
    )

    response = console_user_console_admin(request, target.authentik_user_id)

    target.refresh_from_db()
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert _json_object(response)["error"] == {
        "code": ErrorCode.PERMISSION_DENIED,
        "message": "只有系统管理员可以执行该操作。",
        "details": {},
    }
    assert target.is_console_admin is False


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_put_console_admin_not_found_for_unknown_user() -> None:
    request = _superuser_request(
        "PUT",
        "/console/api/v1/users/missing-user/console-admin",
        body={"is_console_admin": True},
        user_id="people-super-missing",
    )

    response = console_user_console_admin(request, "missing-user")

    assert response.status_code == HTTPStatus.NOT_FOUND
    error = cast("JsonObject", _json_object(response)["error"])
    assert error["code"] == ErrorCode.NOT_FOUND


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_put_console_admin_not_found_for_local_admin_subject() -> None:
    local_admin = UserMirror.objects.create(
        authentik_user_id="local-admin:break-glass",
        name="本地管理员",
    )
    request = _superuser_request(
        "PUT",
        f"/console/api/v1/users/{local_admin.authentik_user_id}/console-admin",
        body={"is_console_admin": True},
        user_id="people-super-local",
    )

    response = console_user_console_admin(request, local_admin.authentik_user_id)

    local_admin.refresh_from_db()
    assert response.status_code == HTTPStatus.NOT_FOUND
    error = cast("JsonObject", _json_object(response)["error"])
    assert error["code"] == ErrorCode.NOT_FOUND
    assert local_admin.is_console_admin is False


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_put_console_admin_rejects_bad_body() -> None:
    target = UserMirror.objects.create(authentik_user_id="people-bad-body")
    request = _superuser_request(
        "PUT",
        f"/console/api/v1/users/{target.authentik_user_id}/console-admin",
        body={"is_console_admin": True, "extra": 1},
        user_id="people-super-body",
    )

    response = console_user_console_admin(request, target.authentik_user_id)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    error = cast("JsonObject", _json_object(response)["error"])
    assert error["code"] == ErrorCode.VALIDATION_ERROR


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
@pytest.mark.parametrize("raw_value", ["yes", "true", "false", 1, 0])
def test_put_console_admin_rejects_non_boolean_flag(raw_value: object) -> None:
    # 管理员标志是权限位: 客户端发错类型必须 422, 不能被 pydantic 静默强转成某个方向。
    target = UserMirror.objects.create(authentik_user_id=f"people-coerce-{raw_value}")
    request = _superuser_request(
        "PUT",
        f"/console/api/v1/users/{target.authentik_user_id}/console-admin",
        body={"is_console_admin": raw_value},
        user_id="people-super-coerce",
    )

    response = console_user_console_admin(request, target.authentik_user_id)

    target.refresh_from_db()
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert target.is_console_admin is False


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_put_console_admin_rejects_self_revocation() -> None:
    actor = UserMirror.objects.create(
        authentik_user_id="people-self-admin",
        is_console_admin=True,
    )
    request = _superuser_request(
        "PUT",
        f"/console/api/v1/users/{actor.authentik_user_id}/console-admin",
        body={"is_console_admin": False},
        user_id=actor.authentik_user_id,
    )

    response = console_user_console_admin(request, actor.authentik_user_id)

    actor.refresh_from_db()
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    error = cast("JsonObject", _json_object(response)["error"])
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert error["message"] == SELF_REVOKE_ADMIN_MESSAGE
    assert actor.is_console_admin is True


@override_settings(EASYAUTH_CONSOLE_SUPERUSER_GROUPS=("easyauth-admins",))
def test_put_console_admin_rejects_wrong_method() -> None:
    target = UserMirror.objects.create(authentik_user_id="people-method")
    request = _superuser_request(
        "GET",
        f"/console/api/v1/users/{target.authentik_user_id}/console-admin",
        user_id="people-super-method",
    )

    response = console_user_console_admin(request, target.authentik_user_id)

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert _json_object(response)["error"] == {
        "code": ErrorCode.VALIDATION_ERROR,
        "message": "请求方法无效。",
        "details": {},
    }


def _superuser_request(
    method: str,
    path: str,
    *,
    body: dict[str, JsonValue] | None = None,
    user_id: str,
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
    _AUTHORITY_GROUPS_BY_UID.clear()
    _AUTHORITY_GROUPS_BY_UID[user_id] = groups
    identity.AuthentikAdminClient.from_settings = lambda: _FakeAuthentikAuthority()  # type: ignore[method-assign]
    request.session[AUTHENTIK_SESSION_KEY] = user_id
    request.session.save()
    request.user = AnonymousUser()
    return request


def _json_object(response: HttpResponse) -> JsonObject:
    payload: JsonObject = cast("JsonObject", json.loads(response.content.decode()))
    assert isinstance(payload, dict)
    return payload
