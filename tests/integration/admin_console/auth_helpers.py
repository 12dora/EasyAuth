from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.conf import settings

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror

if TYPE_CHECKING:
    from collections.abc import Iterable

    import pytest
    from django.test import Client


_AUTHORITY_GROUPS_BY_UID: dict[str, tuple[str, ...]] = {}


class _FakeAuthentikAuthority:
    def user_group_names_by_uid(self, authentik_user_uid: str) -> tuple[str, ...]:
        return _AUTHORITY_GROUPS_BY_UID.get(authentik_user_uid, ())


def install_authentik_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "easyauth.admin_console.identity.AuthentikAdminClient.from_settings",
        lambda: _FakeAuthentikAuthority(),
    )


def reset_authentik_authority() -> None:
    _AUTHORITY_GROUPS_BY_UID.clear()


def set_authentik_groups(username: str, groups: Iterable[str]) -> None:
    _AUTHORITY_GROUPS_BY_UID[username] = _string_values(groups)


def authenticate_console_admin(
    client: Client,
    username: str,
    *,
    groups: Iterable[str] | None = None,
) -> Client:
    return _authenticate_console_user(
        client,
        username,
        groups=_configured_console_superuser_groups() if groups is None else groups,
    )


def authenticate_console_user(client: Client, username: str) -> Client:
    return _authenticate_console_user(client, username, groups=())


def _authenticate_console_user(
    client: Client,
    username: str,
    *,
    groups: Iterable[str],
) -> Client:
    user, _created = UserMirror.objects.get_or_create(authentik_user_id=username)
    normalized_groups = _string_values(groups)
    set_authentik_groups(user.authentik_user_id, normalized_groups)
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()
    return client


def _string_values(value: Iterable[str]) -> tuple[str, ...]:
    return tuple(item for item in cast("Iterable[object]", value) if isinstance(item, str) and item)


def _configured_console_superuser_groups() -> tuple[str, ...]:
    groups = getattr(settings, "EASYAUTH_CONSOLE_SUPERUSER_GROUPS", ())
    if isinstance(groups, str):
        return tuple(group for group in groups.split() if group)
    if isinstance(groups, list | tuple):
        return _string_values(groups)
    return ()
