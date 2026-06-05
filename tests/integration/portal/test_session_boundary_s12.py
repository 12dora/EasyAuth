from __future__ import annotations

from http import HTTPStatus
from typing import Final

import pytest
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, USER_STATUS_DISABLED, UserMirror

pytestmark = pytest.mark.django_db

PORTAL_URL: Final = "/portal/"
LOGIN_URL_PREFIX: Final = "/auth/login/"


def test_portal_redirects_to_login_when_session_has_no_authentik_user() -> None:
    # Given
    client = Client()

    # When
    response = client.get(PORTAL_URL)

    # Then
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"].startswith(LOGIN_URL_PREFIX)


def test_portal_returns_active_user_identity_when_session_is_bound() -> None:
    # Given
    client = Client()
    user = UserMirror.objects.create(
        authentik_user_id="s12-portal-active-user",
        name="门户用户",
        status=USER_STATUS_ACTIVE,
    )
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()

    # When
    response = client.get(PORTAL_URL)

    # Then
    assert response.status_code == HTTPStatus.OK
    assert user.authentik_user_id in response.content.decode()


@pytest.mark.parametrize("authentik_user_id", ["s12-portal-missing-user", "s12-portal-disabled"])
def test_portal_redirects_to_login_and_clears_session_when_bound_user_is_not_active(
    authentik_user_id: str,
) -> None:
    # Given
    client = Client()
    if authentik_user_id == "s12-portal-disabled":
        _ = UserMirror.objects.create(
            authentik_user_id=authentik_user_id,
            status=USER_STATUS_DISABLED,
        )
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = authentik_user_id
    session.save()

    # When
    response = client.get(PORTAL_URL)

    # Then
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"].startswith(LOGIN_URL_PREFIX)
    assert AUTHENTIK_SESSION_KEY not in client.session
