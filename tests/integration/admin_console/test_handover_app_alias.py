from __future__ import annotations

from http import HTTPStatus
from typing import Final

import pytest
from django.test import Client

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import App
from easyauth.lifecycle.models import (
    ACTION_STATUS_BLOCKED,
    HANDOVER_KIND_OFFBOARD,
    HandoverAppAction,
    HandoverTask,
)
from tests.integration.admin_console.auth_helpers import authenticate_console_admin

pytestmark = pytest.mark.django_db

BLOCKED_APPS_URL: Final = "/console/api/v1/lifecycle/handover-blocked-apps"
APP_OPTIONS_URL: Final = "/console/api/v1/lifecycle/handover-app-options"
ALIAS: Final = "海关数据"


def test_console_handover_blocked_apps_emit_app_alias() -> None:
    client = _logged_in_superuser("handover-alias-blocked-admin")
    subject = UserMirror.objects.create(
        authentik_user_id="handover-alias-blocked-subject",
        status=USER_STATUS_ACTIVE,
    )
    app = App.objects.create(app_key="handover-alias-blocked", name="EasyCustoms", alias=ALIAS)
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
        assignee=subject,
        assignee_state="subject",
    )
    _ = HandoverAppAction.objects.create(
        task=task,
        app=app,
        status=ACTION_STATUS_BLOCKED,
        app_key_snapshot=app.app_key,
        app_name_snapshot=app.name,
    )

    response = client.get(BLOCKED_APPS_URL)

    assert response.status_code == HTTPStatus.OK
    apps = response.json()["apps"]
    assert apps == [
        {
            "app_key": app.app_key,
            "app_name": "EasyCustoms",
            "app_alias": ALIAS,
            "blocked_task_count": 1,
        },
    ]


def test_console_handover_app_options_emit_app_alias() -> None:
    client = _logged_in_superuser("handover-alias-options-admin")
    _ = App.objects.create(
        app_key="handover-alias-options",
        name="EasyCustoms",
        alias=ALIAS,
        handover_capability="declared",
    )

    response = client.get(APP_OPTIONS_URL)

    assert response.status_code == HTTPStatus.OK
    item = next(
        option
        for option in response.json()["items"]
        if option["app_key"] == "handover-alias-options"
    )
    assert item["app_name"] == "EasyCustoms"
    assert item["app_alias"] == ALIAS


def _logged_in_superuser(username: str) -> Client:
    client = Client(HTTP_HOST="localhost")
    return authenticate_console_admin(client, username)
