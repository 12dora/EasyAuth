from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from django.conf import settings

from easyauth.accounts.auth import AUTHENTIK_GROUPS_SESSION_KEY, AUTHENTIK_SESSION_KEY
from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import USER_STATUS_ACTIVE, LocalAdminAccount, UserMirror
from easyauth.applications.ownership import ConsoleActor

if TYPE_CHECKING:
    from django.http import HttpRequest

def actor_from_request(request: HttpRequest) -> ConsoleActor | None:
    authentik_user_id = _session_string(request, AUTHENTIK_SESSION_KEY)
    if authentik_user_id == "":
        return None

    # 本地超管以 is_active 为唯一权威: 停用后已有控制台会话必须立即失效, 不能等自然过期。
    if authentik_user_id.startswith(LOCAL_ADMIN_SUBJECT_PREFIX):
        username = authentik_user_id[len(LOCAL_ADMIN_SUBJECT_PREFIX) :]
        if not LocalAdminAccount.objects.filter(username=username, is_active=True).exists():
            _clear_console_session(request)
            return None

    user = UserMirror.objects.filter(
        authentik_user_id=authentik_user_id,
        status=USER_STATUS_ACTIVE,
    ).first()
    if user is None:
        _clear_console_session(request)
        return None

    return ConsoleActor(
        user_id=user.authentik_user_id,
        is_superuser=_is_console_superuser(request),
    )


def _is_console_superuser(request: HttpRequest) -> bool:
    configured_groups = frozenset(
        _string_values(_setting_value("EASYAUTH_CONSOLE_SUPERUSER_GROUPS")),
    )
    session_groups = frozenset(_string_values(request.session.get(AUTHENTIK_GROUPS_SESSION_KEY)))
    return bool(configured_groups and not configured_groups.isdisjoint(session_groups))


def _clear_console_session(request: HttpRequest) -> None:
    request.session.pop(AUTHENTIK_SESSION_KEY, None)
    request.session.pop(AUTHENTIK_GROUPS_SESSION_KEY, None)


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
