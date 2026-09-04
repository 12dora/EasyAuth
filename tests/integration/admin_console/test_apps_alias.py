from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final

import pytest
from django.test import Client

from easyauth.applications.models import App, AppMembership
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    authenticate_console_user,
)

pytestmark = pytest.mark.django_db

APPS_API_URL: Final = "/console/api/v1/apps"


def test_apps_api_creates_and_lists_alias() -> None:
    client = _logged_in_superuser("apps-alias-create-admin")

    response = client.post(
        APPS_API_URL,
        data=dumps(
            {
                "app_key": "apps-alias-create-crm",
                "name": "EasyCustoms",
                "alias": "  海关数据  ",
            },
        ),
        content_type="application/json",
    )

    app = App.objects.get(app_key="apps-alias-create-crm")
    listed = client.get(APPS_API_URL)
    assert response.status_code == HTTPStatus.CREATED
    assert app.alias == "海关数据"
    assert response.json()["app"]["alias"] == "海关数据"
    listed_item = next(
        item for item in listed.json()["data"] if item["app_key"] == app.app_key
    )
    assert listed_item["alias"] == "海关数据"
    assert listed_item["name"] == "EasyCustoms"


def test_apps_api_patches_alias_and_empty_string_clears_it() -> None:
    client = _logged_in_user("apps-alias-patch-owner")
    app = App.objects.create(app_key="apps-alias-patch-crm", name="EasyCustoms")
    _ = AppMembership.objects.create(app=app, user_id="apps-alias-patch-owner", role="owner")

    set_alias = client.patch(
        f"{APPS_API_URL}/{app.app_key}",
        data=dumps({"alias": "  海关数据  "}),
        content_type="application/json",
    )
    app.refresh_from_db()
    assert set_alias.status_code == HTTPStatus.OK
    assert app.alias == "海关数据"
    assert set_alias.json()["app"]["alias"] == "海关数据"

    cleared = client.patch(
        f"{APPS_API_URL}/{app.app_key}",
        data=dumps({"alias": "   "}),
        content_type="application/json",
    )
    app.refresh_from_db()
    assert cleared.status_code == HTTPStatus.OK
    assert app.alias == ""
    assert cleared.json()["app"]["alias"] == ""


def test_apps_api_rejects_alias_longer_than_128() -> None:
    client = _logged_in_superuser("apps-alias-too-long-admin")

    response = client.post(
        APPS_API_URL,
        data=dumps(
            {
                "app_key": "apps-alias-too-long",
                "name": "CRM",
                "alias": "海" * 129,
            },
        ),
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert App.objects.filter(app_key="apps-alias-too-long").exists() is False


def _logged_in_superuser(username: str) -> Client:
    client = Client(HTTP_HOST="localhost")
    return authenticate_console_admin(client, username)


def _logged_in_user(username: str) -> Client:
    client = Client(HTTP_HOST="localhost")
    return authenticate_console_user(client, username)
