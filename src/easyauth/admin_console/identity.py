from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import DatabaseError

from easyauth.accounts.auth import (
    AUTHENTIK_SESSION_KEY,
    clear_auth_session,
)
from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX, current_local_admin
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.ownership import ConsoleActor
from easyauth.integrations.authentik.admin_client import (
    AuthentikAdminClient,
    AuthentikAdminError,
)

if TYPE_CHECKING:
    from django.http import HttpRequest


def actor_from_request(request: HttpRequest) -> ConsoleActor | None:
    authentik_user_id = _session_string(request, AUTHENTIK_SESSION_KEY)
    if authentik_user_id == "":
        return None

    if authentik_user_id.startswith(LOCAL_ADMIN_SUBJECT_PREFIX):
        return _local_admin_actor(request, authentik_user_id)
    return _oidc_actor(request, authentik_user_id)


def _local_admin_actor(request: HttpRequest, authentik_user_id: str) -> ConsoleActor | None:
    try:
        account = current_local_admin(request)
    except DatabaseError:
        return None
    if account is None:
        _clear_console_session(request)
        return None
    if not account.has_second_factor():
        return None
    user = _active_user(authentik_user_id)
    if user is None:
        _clear_console_session(request)
        return None
    return ConsoleActor(user_id=user.authentik_user_id, is_superuser=True)


def _oidc_actor(request: HttpRequest, authentik_user_id: str) -> ConsoleActor | None:
    user = _active_user(authentik_user_id)
    if user is None:
        _clear_console_session(request)
        return None
    return ConsoleActor(
        user_id=user.authentik_user_id,
        is_superuser=_is_console_superuser(request, user),
    )


def _active_user(authentik_user_id: str) -> UserMirror | None:
    try:
        return UserMirror.objects.filter(
            authentik_user_id=authentik_user_id,
            status=USER_STATUS_ACTIVE,
        ).first()
    except DatabaseError:
        return None


def _is_console_superuser(request: HttpRequest, user: UserMirror) -> bool:
    del request
    try:
        authority_groups = frozenset(
            _string_values(
                AuthentikAdminClient.from_settings().user_group_names_by_uid(
                    user.authentik_user_id,
                )
            ),
        )
    except AuthentikAdminError:
        return False
    configured_groups = frozenset(
        _string_values(_setting_value("EASYAUTH_CONSOLE_SUPERUSER_GROUPS")),
    )
    return bool(configured_groups and not configured_groups.isdisjoint(authority_groups))


def _clear_console_session(request: HttpRequest) -> None:
    clear_auth_session(request)


def _session_string(request: HttpRequest, key: str) -> str:
    match request.session.get(key):
        case str() as value:
            return value
        case _:
            return ""


def _setting_value(name: str) -> object:
    return getattr(settings, name, ())


def _string_values(value: object) -> tuple[str, ...]:
    match value:
        case str() as text:
            return tuple(part for part in text.split() if part)
        case Iterable() as values:
            return tuple(item for item in values if isinstance(item, str) and item)
        case _:
            return ()
