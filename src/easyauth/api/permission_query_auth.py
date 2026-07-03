from __future__ import annotations

from typing import Final

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest

from easyauth.api.authentication import AppBearerAuthentication
from easyauth.applications.services import AppPrincipal

_PERMISSION_QUERY_TTL_SETTING: Final = "EASYAUTH_PERMISSION_QUERY_CACHE_TTL_SECONDS"
_DEFAULT_PERMISSION_QUERY_TTL_SECONDS: Final = 300
_INVALID_TTL_ERROR: Final = (
    f"{_PERMISSION_QUERY_TTL_SETTING} 必须是正整数秒; "
    "静默回退默认值会悄悄延长撤销窗口。"
)


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
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ImproperlyConfigured(_INVALID_TTL_ERROR)
    return value
