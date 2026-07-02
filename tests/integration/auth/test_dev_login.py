from __future__ import annotations

from http import HTTPStatus
from typing import Final

import pytest
from django.test import Client, override_settings

from easyauth.accounts.auth import AUTHENTIK_GROUPS_SESSION_KEY, AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror

pytestmark = pytest.mark.django_db

DEV_USER_ID: Final = "local-dev-user"


@override_settings(DEBUG=True)
def test_dev_login_is_disabled_by_default() -> None:
    # Given
    client = Client()

    # When
    response = client.get("/auth/dev-login/")

    # Then
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert AUTHENTIK_SESSION_KEY not in client.session
    assert not UserMirror.objects.exists()


@override_settings(DEBUG=True, EASYAUTH_ENABLE_DEV_LOGIN=True)
def test_dev_login_binds_session_and_redirects_to_next_path() -> None:
    # Given
    client = Client()

    # When
    response = client.get(f"/auth/dev-login/?user_id={DEV_USER_ID}&next=/portal/?tab=requests")

    # Then
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/portal/?tab=requests"
    user = UserMirror.objects.get(authentik_user_id=DEV_USER_ID)
    assert user.status == USER_STATUS_ACTIVE
    assert user.name == "本地开发用户"
    assert user.email == f"{DEV_USER_ID}@dev.local"
    assert client.session[AUTHENTIK_SESSION_KEY] == DEV_USER_ID
    assert client.session[AUTHENTIK_GROUPS_SESSION_KEY] == ["EasyAuth Admins"]


@override_settings(DEBUG=True, EASYAUTH_ENABLE_DEV_LOGIN=True)
def test_dev_login_user_can_open_console_as_default_admin() -> None:
    # Given
    client = Client()

    # When
    login_response = client.get(f"/auth/dev-login/?user_id={DEV_USER_ID}&next=/console/")
    console_response = client.get("/console/")

    # Then
    html = console_response.content.decode()
    assert login_response.status_code == HTTPStatus.FOUND
    assert login_response.headers["Location"] == "/console/"
    assert console_response.status_code == HTTPStatus.OK
    assert 'data-easyauth-react-shell="console"' in html
    assert f'data-current-user-id="{DEV_USER_ID}"' in html
    assert 'data-current-user-role="EasyAuth Admins"' in html


@override_settings(
    DEBUG=True,
    EASYAUTH_ENABLE_DEV_LOGIN=True,
    EASYAUTH_CONSOLE_SUPERUSER_GROUPS=(),
)
def test_dev_login_fails_when_console_superuser_groups_are_empty() -> None:
    # Given
    client = Client()

    # When
    response = client.get(f"/auth/dev-login/?user_id={DEV_USER_ID}")

    # Then
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.headers["Content-Type"].startswith("text/plain")
    assert "EASYAUTH_CONSOLE_SUPERUSER_GROUPS" in response.content.decode()
    assert AUTHENTIK_SESSION_KEY not in client.session
    assert AUTHENTIK_GROUPS_SESSION_KEY not in client.session
    assert not UserMirror.objects.exists()


@override_settings(DEBUG=True, EASYAUTH_ENABLE_DEV_LOGIN=True)
@pytest.mark.parametrize(
    "unsafe_next",
    [
        "https://evil.example.test/portal/",
        "//evil.example.test/portal/",
        "portal/",
    ],
)
def test_dev_login_ignores_unsafe_next_values(unsafe_next: str) -> None:
    # Given
    client = Client()

    # When
    response = client.get("/auth/dev-login/", {"next": unsafe_next})

    # Then
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/portal/"
