from __future__ import annotations

from typing import TYPE_CHECKING, Final

from django.conf import settings as django_settings

from easyauth.accounts.auth import VerifiedOidcClaims, bind_oidc_session, clear_auth_session
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror

if TYPE_CHECKING:
    from django.http import HttpRequest

DEFAULT_DEV_LOGIN_USER_ID: Final = "dev-user"
DEV_LOGIN_NAME: Final = "本地开发用户"
SETTING_CONSOLE_SUPERUSER_GROUPS: Final = "EASYAUTH_CONSOLE_SUPERUSER_GROUPS"


class DevLoginConfigurationError(RuntimeError):
    pass


def dev_login_is_enabled() -> bool:
    return _bool_setting("DEBUG") and _bool_setting("EASYAUTH_ENABLE_DEV_LOGIN")


def bind_dev_login_session(request: HttpRequest, user_id: str = DEFAULT_DEV_LOGIN_USER_ID) -> UserMirror:
    groups = _string_tuple_setting(SETTING_CONSOLE_SUPERUSER_GROUPS)
    if not groups:
        clear_auth_session(request)
        raise DevLoginConfigurationError(f"{SETTING_CONSOLE_SUPERUSER_GROUPS} is required for dev login")

    normalized_user_id = user_id.strip() or DEFAULT_DEV_LOGIN_USER_ID
    user = bind_oidc_session(
        request,
        VerifiedOidcClaims(
            subject=normalized_user_id,
            name=DEV_LOGIN_NAME,
            email=f"{normalized_user_id}@dev.local",
            groups=groups,
        ),
    )
    if user.status != USER_STATUS_ACTIVE:
        user.status = USER_STATUS_ACTIVE
        user.full_clean()
        user.save(update_fields=["status", "updated_at"])
    return user


def _bool_setting(name: str) -> bool:
    value: bool | None = getattr(django_settings, name, None)
    match value:
        case bool() as bool_value:
            return bool_value
        case _:
            return False


def _string_tuple_setting(name: str) -> tuple[str, ...]:
    value: tuple[str, ...] | list[str] | str | None = getattr(
        django_settings,
        name,
        None,
    )
    match value:
        case tuple() as strings:
            return tuple(item for item in strings if item)
        case list() as strings:
            return tuple(item for item in strings if item)
        case str() as text:
            return tuple(item.strip() for item in text.split(",") if item.strip())
        case _:
            return ()
