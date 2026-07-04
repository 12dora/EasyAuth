from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, cast

import pytest
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_DISABLED, UserMirror

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

USERS_API_URL: Final = "/console/api/v1/users"


def test_user_search_matches_name_email_and_id() -> None:
    client = _logged_in_console_user("user-search-admin")
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

    response = client.get(USERS_API_URL, {"q": "sales"})

    assert response.status_code == HTTPStatus.OK
    payload = cast("dict[str, JsonValue]", response.json())
    items = cast("list[dict[str, JsonValue]]", payload["data"])
    assert [item["user_id"] for item in items] == ["ak_uid_sales_001"]
    assert items[0]["name"] == "销售运行用户"
    assert items[0]["email"] == "sales.runtime@example.com"
    assert items[0]["department"] == "销售部"

    response_by_name = client.get(USERS_API_URL, {"q": "运维"})
    payload_by_name = cast("dict[str, JsonValue]", response_by_name.json())
    items_by_name = cast("list[dict[str, JsonValue]]", payload_by_name["data"])
    assert [item["user_id"] for item in items_by_name] == ["ak_uid_ops_001"]


def test_user_search_excludes_inactive_users() -> None:
    client = _logged_in_console_user("user-search-active-admin")
    _ = UserMirror.objects.create(
        authentik_user_id="ak_uid_departed_001",
        name="离职用户",
        status=USER_STATUS_DISABLED,
    )

    response = client.get(USERS_API_URL, {"q": "离职"})

    assert response.status_code == HTTPStatus.OK
    payload = cast("dict[str, JsonValue]", response.json())
    assert payload["data"] == []


def test_user_search_requires_console_session() -> None:
    client = Client(HTTP_HOST="localhost")

    response = client.get(USERS_API_URL, {"q": "sales"})

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_user_search_rejects_non_get() -> None:
    client = _logged_in_console_user("user-search-method-admin")

    response = client.post(USERS_API_URL, data={}, content_type="application/json")

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def _logged_in_console_user(username: str) -> Client:
    _ = UserMirror.objects.create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = username
    session["easyauth_authentik_groups"] = ["EasyAuth Admins"]
    session.save()
    return client
