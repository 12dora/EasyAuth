from __future__ import annotations

from http import HTTPStatus
from typing import Final

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AppMembership
from tests.integration.admin_console.auth_helpers import authenticate_console_admin

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "membership-user-names-password"
APPS_API_URL: Final = "/console/api/v1/apps"


def test_memberships_list_includes_user_names_from_mirrors() -> None:
    client = _logged_in_superuser("membership-names-admin")
    app = App.objects.create(app_key="membership-names-app", name="CRM")
    named = AppMembership.objects.create(
        app=app,
        user_id="membership-named-user",
        role="owner",
    )
    unnamed = AppMembership.objects.create(
        app=app,
        user_id="membership-unnamed-user",
        role="developer",
    )
    missing = AppMembership.objects.create(
        app=app,
        user_id="membership-missing-user",
        role="developer",
    )
    _ = UserMirror.objects.create(
        authentik_user_id="membership-named-user",
        name="胡玉琴A",
    )
    _ = UserMirror.objects.create(authentik_user_id="membership-unnamed-user")

    response = client.get(f"{APPS_API_URL}/{app.app_key}/memberships")

    assert response.status_code == HTTPStatus.OK
    by_id = {item["id"]: item for item in response.json()["data"]}
    assert by_id[named.id]["user_name"] == "胡玉琴A"
    assert by_id[unnamed.id]["user_name"] == ""
    assert by_id[missing.id]["user_name"] == ""


def test_memberships_list_loads_user_names_in_one_query() -> None:
    client = _logged_in_superuser("membership-names-query-admin")
    app = App.objects.create(app_key="membership-names-query-app", name="CRM")
    for index in range(6):
        user_id = f"membership-query-user-{index}"
        _ = AppMembership.objects.create(app=app, user_id=user_id, role="developer")
        _ = UserMirror.objects.create(authentik_user_id=user_id, name=f"用户{index}")

    with CaptureQueriesContext(connection) as captured:
        response = client.get(f"{APPS_API_URL}/{app.app_key}/memberships")

    assert response.status_code == HTTPStatus.OK
    assert len(response.json()["data"]) == 6
    assert _usermirror_in_lookups(captured) == 1


def _usermirror_in_lookups(captured: CaptureQueriesContext) -> int:
    return sum(
        1
        for query in captured
        if "accounts_usermirror" in query["sql"].lower()
        and "authentik_user_id" in query["sql"].lower()
        and " in (" in query["sql"].lower()
    )


def _logged_in_superuser(username: str) -> Client:
    client = Client(HTTP_HOST="localhost")
    return authenticate_console_admin(client, username)
