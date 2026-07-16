from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from django.test import RequestFactory

from easyauth.accounts.models import DingTalkUserMirror, UserMirror
from easyauth.api import notify_views
from easyauth.applications.models import CAPABILITY_NOTIFY, App, AppCapability
from easyauth.applications.services import AppPrincipal
from easyauth.notify.models import NotifyMessage

if TYPE_CHECKING:
    from django.http import HttpRequest

pytestmark = pytest.mark.django_db


def test_notify_gate_requires_current_credential_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key="notify-gate", name="Notify Gate")
    _ = AppCapability.objects.create(
        app=app,
        capability=CAPABILITY_NOTIFY,
        enabled=True,
    )
    principal = AppPrincipal(
        app_id=app.id,
        app_key=app.app_key,
        credential_type="static_token",
        credential_id=1,
    )

    def authenticate(_token: str) -> AppPrincipal:
        return principal

    monkeypatch.setattr(notify_views, "authenticate_permission_query_token", authenticate)
    request: HttpRequest = RequestFactory().post(
        f"/api/v1/apps/{app.app_key}/notify/messages",
        data={"recipients": ["missing"], "template": "text", "content": "blocked"},
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer credential-without-notify",
    )
    response = notify_views.notify_messages_create(request, app.app_key)
    assert response.status_code == HTTPStatus.FORBIDDEN


def test_notify_accept_without_channel_returns_503_without_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = App.objects.create(app_key="notify-no-channel", name="Notify No Channel")
    _ = AppCapability.objects.create(
        app=app,
        capability=CAPABILITY_NOTIFY,
        enabled=True,
    )
    _ = DingTalkUserMirror.objects.create(
        source_slug="dingtalk",
        corp_id="notify-corp",
        user_id="notify-user",
        name="Notify User",
        status="active",
    )
    _ = UserMirror.objects.create(
        authentik_user_id="notify-authentik-user",
        dingtalk_userid="notify-user",
        dingtalk_corp_id="notify-corp",
    )
    principal = AppPrincipal(
        app_id=app.id,
        app_key=app.app_key,
        credential_type="static_token",
        credential_id=2,
        capabilities=frozenset({CAPABILITY_NOTIFY}),
    )

    def authenticate(_token: str) -> AppPrincipal:
        return principal

    monkeypatch.setattr(notify_views, "authenticate_permission_query_token", authenticate)
    request: HttpRequest = RequestFactory().post(
        f"/api/v1/apps/{app.app_key}/notify/messages",
        data={
            "recipients": ["notify-authentik-user"],
            "template": "text",
            "content": "must not persist",
        },
        content_type="application/json",
        HTTP_AUTHORIZATION="Bearer notify-without-channel",
    )
    response = notify_views.notify_messages_create(request, app.app_key)
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert b"DEPENDENCY_UNAVAILABLE" in response.content
    assert NotifyMessage.objects.filter(app=app).exists() is False
