from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, cast

import pytest
from django.contrib.auth.models import User
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_DISABLED, UserMirror

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

USERS_API_URL: Final = "/console/api/v1/users"
USER_OPTIONS_API_URL: Final = "/console/api/v1/user-options"
LOGIN_VALUE: Final = "user-search-password"


def test_user_search_matches_name_email_and_id() -> None:
    client = _logged_in_superuser("user-search-admin")
    _ = UserMirror.objects.create(
        authentik_user_id="ak_uid_sales_001",
        name="销售运行用户",
        email="sales.runtime@example.com",
        department="销售部",
    )
    _ = UserMirror.objects.create(
        authentik_user_id="ak_uid_ops_001",
        name="运维用户",
        email="ops@example.com",
    )

    response = client.get(USER_OPTIONS_API_URL, {"q": "sales"})

    assert response.status_code == HTTPStatus.OK
    payload = cast("dict[str, JsonValue]", response.json())
    items = cast("list[dict[str, JsonValue]]", payload["data"])
    assert [item["user_id"] for item in items] == ["ak_uid_sales_001"]
    assert items[0]["name"] == "销售运行用户"
    assert set(items[0]) == {"user_id", "name"}

    response_by_name = client.get(USER_OPTIONS_API_URL, {"q": "运维"})
    payload_by_name = cast("dict[str, JsonValue]", response_by_name.json())
    items_by_name = cast("list[dict[str, JsonValue]]", payload_by_name["data"])
    assert [item["user_id"] for item in items_by_name] == ["ak_uid_ops_001"]


def test_user_search_excludes_inactive_users() -> None:
    client = _logged_in_superuser("user-search-active-admin")
    _ = UserMirror.objects.create(
        authentik_user_id="ak_uid_departed_001",
        name="离职用户",
        status=USER_STATUS_DISABLED,
    )

    response = client.get(USER_OPTIONS_API_URL, {"q": "离职"})

    assert response.status_code == HTTPStatus.OK
    payload = cast("dict[str, JsonValue]", response.json())
    assert payload["data"] == []


def test_approver_search_includes_active_local_admin() -> None:
    client = _logged_in_superuser("user-search-approver-admin")
    local_admin = UserMirror.objects.create(
        authentik_user_id="local-admin:admin",
        name="本地管理员 admin",
    )

    employee_response = client.get(USER_OPTIONS_API_URL, {"q": "admin"})
    employee_payload = cast("dict[str, JsonValue]", employee_response.json())
    employee_items = cast("list[dict[str, JsonValue]]", employee_payload["data"])

    response = client.get(USER_OPTIONS_API_URL, {"q": "admin", "purpose": "approver"})

    payload = cast("dict[str, JsonValue]", response.json())
    items = cast("list[dict[str, JsonValue]]", payload["data"])
    assert employee_response.status_code == HTTPStatus.OK
    assert all(item["user_id"] != local_admin.authentik_user_id for item in employee_items)
    assert response.status_code == HTTPStatus.OK
    assert any(item["user_id"] == local_admin.authentik_user_id for item in items)


def test_user_search_requires_console_session() -> None:
    client = Client(HTTP_HOST="localhost")

    response = client.get(USER_OPTIONS_API_URL, {"q": "sales"})

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_user_search_rejects_non_get() -> None:
    client = _logged_in_superuser("user-search-method-admin")

    response = client.post(USER_OPTIONS_API_URL, data={}, content_type="application/json")

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_user_search_rejects_empty_query() -> None:
    client = _logged_in_superuser("user-search-empty-admin")

    response = client.get(USER_OPTIONS_API_URL)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_people_page_rejects_non_superuser() -> None:
    client = _logged_in_console_user("people-ordinary-user")
    _ = UserMirror.objects.create(
        authentik_user_id="people-sensitive-departed",
        status=USER_STATUS_DISABLED,
    )

    response = client.get(USERS_API_URL, {"page": "1", "page_size": "20"})

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert "people-sensitive-departed" not in response.content.decode()


def test_people_page_allows_superuser() -> None:
    client = _logged_in_superuser("people-superuser")
    person = UserMirror.objects.create(
        authentik_user_id="people-visible-departed",
        name="已离职员工",
        email="departed@example.com",
        department="历史部门",
        status=USER_STATUS_DISABLED,
    )

    response = client.get(USERS_API_URL, {"page": "1", "page_size": "20"})

    payload = cast("dict[str, JsonValue]", response.json())
    items = cast("list[dict[str, JsonValue]]", payload["data"])
    assert response.status_code == HTTPStatus.OK
    assert any(item["user_id"] == person.authentik_user_id for item in items)


def test_user_search_rejects_non_superuser() -> None:
    client = _logged_in_console_user("user-search-ordinary-user")

    response = client.get(USER_OPTIONS_API_URL, {"q": "user"})

    assert response.status_code == HTTPStatus.FORBIDDEN


def _logged_in_console_user(username: str) -> Client:
    _ = UserMirror.objects.create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = username
    session["easyauth_authentik_groups"] = []
    session.save()
    return client


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client
