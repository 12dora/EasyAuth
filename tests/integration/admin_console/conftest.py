from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import cast

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_GROUPS_SESSION_KEY, AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror


@pytest.fixture(autouse=True)
def bridge_legacy_client_login_to_authentik_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_login = cast("Callable[..., bool]", Client.login)

    def login_with_authentik_session(self: Client, **credentials: object) -> bool:
        authenticated = original_login(self, **credentials)
        if not authenticated:
            return False

        username = credentials.get("username")
        if not isinstance(username, str) or username == "":
            return authenticated

        user, _created = UserMirror.objects.get_or_create(authentik_user_id=username)
        session = self.session
        session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
        if _is_django_superuser(username):
            session[AUTHENTIK_GROUPS_SESSION_KEY] = list(
                _configured_console_superuser_groups(),
            )
        session.save()
        return authenticated

    monkeypatch.setattr(Client, "login", login_with_authentik_session)


def _is_django_superuser(username: str) -> bool:
    user_model = get_user_model()
    return user_model.objects.filter(username=username, is_superuser=True).exists()


def _configured_console_superuser_groups() -> tuple[str, ...]:
    groups = getattr(settings, "EASYAUTH_CONSOLE_SUPERUSER_GROUPS", ())
    if isinstance(groups, str):
        return tuple(group for group in groups.split() if group)
    if not isinstance(groups, Iterable):
        return ()
    iterable_groups = cast("Iterable[object]", groups)
    return tuple(group for group in iterable_groups if isinstance(group, str) and group)
