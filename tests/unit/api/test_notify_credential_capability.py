from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from django.test import RequestFactory

from easyauth.api import notify_views
from easyauth.applications.models import CAPABILITY_NOTIFY, App, AppCapability
from easyauth.applications.services import AppPrincipal

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
