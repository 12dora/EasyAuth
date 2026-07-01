from __future__ import annotations

from typing import Final

from django.conf import settings
from django.http import HttpRequest

from easyauth.api.authentication import AppBearerAuthentication
from easyauth.applications.services import AppPrincipal

_PERMISSION_QUERY_TTL_SETTING: Final = "EASYAUTH_PERMISSION_QUERY_CACHE_TTL_SECONDS"
_DEFAULT_PERMISSION_QUERY_TTL_SECONDS: Final = 300


def authenticate_permission_query_token(token: str) -> AppPrincipal:
    request = HttpRequest()
    request.META["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    result = AppBearerAuthentication().authenticate(request)
    match result:
        case (AppPrincipal() as principal, None):
            return principal
        case None:
            raise AssertionError


def permission_query_ttl_seconds() -> int:
    value: object = getattr(
        settings,
        _PERMISSION_QUERY_TTL_SETTING,
        _DEFAULT_PERMISSION_QUERY_TTL_SECONDS,
    )
    if isinstance(value, bool):
        return _DEFAULT_PERMISSION_QUERY_TTL_SECONDS
    if isinstance(value, int) and value > 0:
        return value
    return _DEFAULT_PERMISSION_QUERY_TTL_SECONDS
