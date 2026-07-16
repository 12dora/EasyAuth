from __future__ import annotations

from http import HTTPStatus

import pytest
from django.test import RequestFactory

from easyauth.api import notify_views
from easyauth.applications.models import CAPABILITY_NOTIFY, App, AppCapability
from easyauth.applications.services import AppPrincipal

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("credential_capabilities", "expected_status"),
    [
        (frozenset(), HTTPStatus.FORBIDDEN),
        (frozenset({CAPABILITY_NOTIFY}), HTTPStatus.OK),
    ],
)
def test_notify_gate_requires_current_credential_capability(
    monkeypatch: pytest.MonkeyPatch,
    credential_capabilities: frozenset[str],
    expected_status: HTTPStatus,
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
        capabilities=credential_capabilities,
    )
    monkeypatch.setattr(
        notify_views,
        "_authenticate_and_authfail_throttle",
        lambda _request: principal,
    )
    result = notify_views._authenticate_notify_capability(  # noqa: SLF001
        RequestFactory().get("/"),
        app.app_key,
    )
    if expected_status == HTTPStatus.OK:
        assert isinstance(result, tuple)
        assert result == (app, principal)
    else:
        assert result.status_code == expected_status
