from __future__ import annotations

from typing import TYPE_CHECKING, Final, override

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from easyauth.applications.oauth import (
    APP_CREDENTIAL_TYPE_OAUTH_CLIENT,
    OAuthClientAppDisabledError,
    OAuthClientAuthenticationError,
    OAuthClientService,
)
from easyauth.applications.services import (
    APP_CREDENTIAL_TYPE_STATIC_TOKEN,
    AppPrincipal,
    StaticTokenAppDisabledError,
    StaticTokenAuthenticationError,
    StaticTokenService,
)

if TYPE_CHECKING:
    from django.http import HttpRequest

_AUTH_SCHEME: Final = "Bearer"
_INVALID_CREDENTIAL_MESSAGE: Final = "应用认证凭据无效。"
_DISABLED_APP_MESSAGE: Final = "应用已禁用。"


class AppBearerAuthentication(BaseAuthentication):
    @override
    def authenticate(self, request: HttpRequest) -> tuple[AppPrincipal, None] | None:
        raw_header: str | None = request.META.get("HTTP_AUTHORIZATION")
        if raw_header is None:
            return None

        match _parse_bearer_header(raw_header):
            case str() as token:
                pass
            case None:
                raise AuthenticationFailed(_INVALID_CREDENTIAL_MESSAGE)

        try:
            principal = StaticTokenService.authenticate_for_api(token)
        except StaticTokenAppDisabledError as error:
            raise PermissionDenied(_DISABLED_APP_MESSAGE) from error
        except StaticTokenAuthenticationError:
            try:
                principal = OAuthClientService.authenticate_access_token_for_api(token)
            except OAuthClientAppDisabledError as oauth_error:
                raise PermissionDenied(_DISABLED_APP_MESSAGE) from oauth_error
            except OAuthClientAuthenticationError as oauth_error:
                raise AuthenticationFailed(_INVALID_CREDENTIAL_MESSAGE) from oauth_error

        return principal, None

    @override
    def authenticate_header(self, request: HttpRequest) -> str:
        return _AUTH_SCHEME


def _parse_bearer_header(raw_header: str) -> str | None:
    scheme, separator, token = raw_header.partition(" ")
    if not separator:
        return None
    # RFC 7235 认证方案不区分大小写。
    if scheme.lower() != _AUTH_SCHEME.lower():
        return None
    if not token:
        return None
    return token


__all__ = [
    "APP_CREDENTIAL_TYPE_OAUTH_CLIENT",
    "APP_CREDENTIAL_TYPE_STATIC_TOKEN",
    "AppBearerAuthentication",
    "AppPrincipal",
]
