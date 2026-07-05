from __future__ import annotations

from django.http import HttpResponse
from django.test import override_settings

from easyauth.accounts.logout_state import (
    LOGGED_OUT_COOKIE_NAME,
    mark_browser_logged_out,
)


@override_settings(DEBUG=False)
def test_logged_out_cookie_is_secure_in_production() -> None:
    response = HttpResponse()
    mark_browser_logged_out(response)
    cookie = response.cookies[LOGGED_OUT_COOKIE_NAME]
    # 与 SESSION_COOKIE_SECURE/CSRF_COOKIE_SECURE 口径一致。
    assert cookie["secure"] is True
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"


@override_settings(DEBUG=True)
def test_logged_out_cookie_not_secure_in_debug() -> None:
    response = HttpResponse()
    mark_browser_logged_out(response)
    assert response.cookies[LOGGED_OUT_COOKIE_NAME]["secure"] == ""
