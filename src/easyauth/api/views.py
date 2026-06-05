from __future__ import annotations

from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Final

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from easyauth.api.authentication import AppBearerAuthentication
from easyauth.api.errors import ErrorCode, build_error_response
from easyauth.api.serializers import (
    PermissionQueryResponseInput,
    PermissionQueryResponseSerializer,
)
from easyauth.applications.models import App
from easyauth.applications.services import AppPrincipal
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.query import PermissionSnapshot, resolve_user_permissions

PERMISSION_QUERY_EVENT: Final = "app_permission_queried"
PERMISSION_QUERY_TARGET_TYPE: Final = "user_permission"
_AUTHENTICATION_FAILED_MESSAGE: Final = "应用认证凭据无效。"
_PERMISSION_DENIED_MESSAGE: Final = "应用无权查询该资源。"
_PERMISSION_QUERY_TTL_SETTING: Final = "EASYAUTH_PERMISSION_QUERY_CACHE_TTL_SECONDS"
_DEFAULT_PERMISSION_QUERY_TTL_SECONDS: Final = 300


def query_user_permissions(request: HttpRequest, app_key: str, user_id: str) -> JsonResponse:
    match _authenticate_app(request):
        case AppPrincipal() as principal:
            pass
        case JsonResponse() as response:
            return response

    if principal.app_key != app_key:
        return _permission_denied_response()

    app = App.objects.get(id=principal.app_id)
    snapshot = resolve_user_permissions(user=user_id, app=app)
    expires_at: datetime = _permission_query_expires_at(snapshot)
    payload: PermissionQueryResponseInput = {
        "user_id": snapshot.user_id,
        "app_key": snapshot.app_key,
        "roles": list(snapshot.roles),
        "permissions": list(snapshot.permissions),
        "version": snapshot.version,
        "expires_at": expires_at.isoformat(),
    }
    serializer = PermissionQueryResponseSerializer(data=payload)
    if not serializer.is_valid():
        return JsonResponse(
            build_error_response(
                ErrorCode.INTERNAL_ERROR,
                "权限查询响应无法序列化。",
                {"serializer_errors": str(serializer.errors)},
            ),
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
        )

    _record_permission_query(principal=principal, snapshot=snapshot)
    return JsonResponse(serializer.data, status=HTTPStatus.OK)


def _authenticate_app(request: HttpRequest) -> AppPrincipal | JsonResponse:
    try:
        result = AppBearerAuthentication().authenticate(request)
    except AuthenticationFailed:
        return _authentication_failed_response()
    except PermissionDenied:
        return _permission_denied_response()

    match result:
        case (AppPrincipal() as principal, None):
            return principal
        case None:
            return _authentication_failed_response()


def _permission_query_expires_at(snapshot: PermissionSnapshot) -> datetime:
    ttl_expires_at = timezone.now() + timedelta(seconds=_permission_query_ttl_seconds())
    grant_expires_at = snapshot.grant_expires_at
    if grant_expires_at is None:
        return ttl_expires_at
    return min(ttl_expires_at, grant_expires_at)


def _permission_query_ttl_seconds() -> int:
    value: int | bool | str = getattr(
        settings,
        _PERMISSION_QUERY_TTL_SETTING,
        _DEFAULT_PERMISSION_QUERY_TTL_SECONDS,
    )
    if isinstance(value, bool):
        return _DEFAULT_PERMISSION_QUERY_TTL_SECONDS
    if isinstance(value, int):
        return value
    return _DEFAULT_PERMISSION_QUERY_TTL_SECONDS


def _record_permission_query(*, principal: AppPrincipal, snapshot: PermissionSnapshot) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="app",
            actor_id=principal.app_key,
            action=PERMISSION_QUERY_EVENT,
            target_type=PERMISSION_QUERY_TARGET_TYPE,
            target_id=f"{snapshot.user_id}:{snapshot.app_key}",
            metadata={
                "app_key": snapshot.app_key,
                "user_id": snapshot.user_id,
                "version": snapshot.version,
                "role_count": len(snapshot.roles),
                "permission_count": len(snapshot.permissions),
                "credential_type": principal.credential_type,
                "credential_id": principal.credential_id,
            },
        ),
    )


def _authentication_failed_response() -> JsonResponse:
    return JsonResponse(
        build_error_response(ErrorCode.AUTHENTICATION_FAILED, _AUTHENTICATION_FAILED_MESSAGE),
        status=HTTPStatus.UNAUTHORIZED,
    )


def _permission_denied_response() -> JsonResponse:
    return JsonResponse(
        build_error_response(ErrorCode.PERMISSION_DENIED, _PERMISSION_DENIED_MESSAGE),
        status=HTTPStatus.FORBIDDEN,
    )
