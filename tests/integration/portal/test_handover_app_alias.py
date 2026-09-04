from __future__ import annotations

from http import HTTPStatus
from typing import Final

import pytest
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, DingTalkUserOrgContext, UserMirror
from easyauth.applications.models import App

pytestmark = pytest.mark.django_db

SOURCE: Final = "src-alias"
CORP: Final = "corp-alias"
ALIAS: Final = "海关数据"


def test_portal_handover_app_options_emit_app_alias() -> None:
    manager = _user("handover-alias-mgr", dtuid="alias-mgr")
    subject = _user("handover-alias-subj", dtuid="alias-subj")
    _ = DingTalkUserOrgContext.objects.create(
        source_slug=SOURCE,
        corp_id=CORP,
        user_id=subject.dingtalk_userid,
        manager_chain=[{"user_id": "alias-mgr"}],
        stale=False,
    )
    _ = App.objects.create(
        app_key="portal-alias-options",
        name="EasyCustoms",
        alias=ALIAS,
        handover_capability="declared",
    )
    client = _login(Client(), manager)

    response = client.get(
        "/portal/api/v1/handover-app-options",
        {"subject_user_id": subject.authentik_user_id},
    )

    assert response.status_code == HTTPStatus.OK
    item = next(
        option
        for option in response.json()["items"]
        if option["app_key"] == "portal-alias-options"
    )
    assert item["app_name"] == "EasyCustoms"
    assert item["app_alias"] == ALIAS


def _user(uid: str, *, dtuid: str) -> UserMirror:
    return UserMirror.objects.create(
        authentik_user_id=uid,
        name=uid,
        status=USER_STATUS_ACTIVE,
        dingtalk_source_slug=SOURCE,
        dingtalk_corp_id=CORP,
        dingtalk_userid=dtuid,
    )


def _login(client: Client, user: UserMirror) -> Client:
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()
    return client
