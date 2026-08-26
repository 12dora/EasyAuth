from __future__ import annotations

from typing import Final

from django.http import HttpRequest, JsonResponse
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from easyauth.api.directory_responses import (
    authentication_failed_response,
    permission_denied_response,
    too_many_requests_response,
)
from easyauth.api.permission_query_auth import authenticate_permission_query_token
from easyauth.applications.capabilities import (
    app_capability_enabled,
    credential_capability_enabled,
)
from easyauth.applications.models import CAPABILITY_DIRECTORY, App
from easyauth.applications.services import AppPrincipal
from easyauth.config.rate_limit import client_ip, over_limit, rate_limit_exceeded

_PERMISSION_DENIED_MESSAGE: Final = "应用无权查询该资源。"
_DIRECTORY_CAPABILITY_DENIED_MESSAGE: Final = "应用未开通目录能力。"
_AUTH_SCHEME: Final = "Bearer"
_AUTH_FAIL_LIMIT: Final = 30
_AUTH_FAIL_WINDOW_SECONDS: Final = 300
_QUERY_RATE_LIMIT: Final = 240
_QUERY_RATE_WINDOW_SECONDS: Final = 60
_AUTH_FAIL_NAMESPACE: Final = "directory-authfail"
_RATE_NAMESPACE: Final = "directory-rate"


def authenticate_capability_and_throttle(
    request: HttpRequest,
    app_key: str,
) -> AppPrincipal | JsonResponse:
    match _authenticate_and_throttle(request):
        case AppPrincipal() as principal:
            pass
        case JsonResponse() as response:
            return response
    if principal.app_key != app_key:
        return permission_denied_response(_PERMISSION_DENIED_MESSAGE)
    app = App.objects.filter(id=principal.app_id).first()
    if app is None:
        return authentication_failed_response()
    if not app_capability_enabled(
        app.id,
        CAPABILITY_DIRECTORY,
    ) or not credential_capability_enabled(principal, CAPABILITY_DIRECTORY):
        return permission_denied_response(_DIRECTORY_CAPABILITY_DENIED_MESSAGE)
    return principal


def _authenticate_and_throttle(request: HttpRequest) -> AppPrincipal | JsonResponse:
    # 认证失败按 IP 限流, 认证成功后按 credential 限请求速率(纵深防御)。
    ip = client_ip(request)
    if over_limit(_AUTH_FAIL_NAMESPACE, ip, limit=_AUTH_FAIL_LIMIT):
        return too_many_requests_response(_AUTH_FAIL_WINDOW_SECONDS)
    match _authenticate_app(request):
        case AppPrincipal() as principal:
            pass
        case JsonResponse() as response:
            _ = rate_limit_exceeded(
                _AUTH_FAIL_NAMESPACE,
                ip,
                limit=_AUTH_FAIL_LIMIT,
                window_seconds=_AUTH_FAIL_WINDOW_SECONDS,
            )
            return response
    if rate_limit_exceeded(
        _RATE_NAMESPACE,
        principal.credential_id,
        limit=_QUERY_RATE_LIMIT,
        window_seconds=_QUERY_RATE_WINDOW_SECONDS,
    ):
        return too_many_requests_response(_QUERY_RATE_WINDOW_SECONDS)
    return principal


def _authenticate_app(request: HttpRequest) -> AppPrincipal | JsonResponse:
    token = _bearer_token_from_request(request)
    if token is None:
        return authentication_failed_response()
    try:
        return authenticate_permission_query_token(token)
    except AuthenticationFailed:
        return authentication_failed_response()
    except PermissionDenied:
        return permission_denied_response(_PERMISSION_DENIED_MESSAGE)


def _bearer_token_from_request(request: HttpRequest) -> str | None:
    raw_header: str | None = request.META.get("HTTP_AUTHORIZATION")
    if raw_header is None:
        return None
    scheme, separator, token = raw_header.partition(" ")
    if not separator:
        return None
    if scheme.lower() != _AUTH_SCHEME.lower():
        return None
    if not token:
        return None
    return token
