from __future__ import annotations

import logging
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Final

from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from easyauth.api.errors import ErrorCode, build_error_response
from easyauth.api.permission_query_auth import (
    authenticate_permission_query_token,
    permission_query_ttl_seconds,
)
from easyauth.api.permission_query_payloads import expanded_grant_payload
from easyauth.api.serializers import (
    PermissionQueryResponseInput,
    PermissionQueryResponseSerializer,
)
from easyauth.applications.models import App
from easyauth.applications.services import AppPrincipal
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.managed_users import ManagedUsersResolutionUnavailableError
from easyauth.grants.query import PermissionSnapshot, resolve_user_permissions

logger = logging.getLogger(__name__)

PERMISSION_QUERY_EVENT: Final = "app_permission_queried"
PERMISSION_QUERY_TARGET_TYPE: Final = "user_permission"
_AUTHENTICATION_FAILED_MESSAGE: Final = "应用认证凭据无效。"
_PERMISSION_DENIED_MESSAGE: Final = "应用无权查询该资源。"
_AUTH_SCHEME: Final = "Bearer"


def query_user_permissions(request: HttpRequest, app_key: str, user_id: str) -> JsonResponse:
    match _authenticate_app(request):
        case AppPrincipal() as principal:
            pass
        case JsonResponse() as response:
            return response

    if principal.app_key != app_key:
        return _permission_denied_response()

    app = App.objects.filter(id=principal.app_id).first()
    if app is None:
        # 凭据校验后 App 行被并发删除; 按认证失败处理而非 500。
        return _authentication_failed_response()
    try:
        snapshot = resolve_user_permissions(user=user_id, app=app)
    except ManagedUsersResolutionUnavailableError as error:
        # 目录瞬时故障必须显式失败, 下游不能把缺失的 MANAGED_USERS 当成真实撤权。
        return JsonResponse(
            build_error_response(ErrorCode.DEPENDENCY_UNAVAILABLE, str(error)),
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        )
    expires_at: datetime = _permission_query_expires_at(snapshot)
    payload: PermissionQueryResponseInput = {
        "user_id": snapshot.user_id,
        "app_key": snapshot.app_key,
        "groups": [
            {"key": group.key, "kind": group.kind, "name": group.name}
            for group in snapshot.groups
        ],
        "grants": [
            expanded_grant_payload(grant)
            for grant in snapshot.grants
        ],
        "grant_version": snapshot.grant_version,
        "catalog_version": snapshot.catalog_version,
        "snapshot_version": snapshot.snapshot_version,
        "expires_at": expires_at.isoformat(),
    }
    serializer = PermissionQueryResponseSerializer(data=payload)
    if not serializer.is_valid():
        # 序列化细节只进服务端日志, 不向调用方回显内部字段结构。
        logger.error(
            "permission query response serialization failed: app=%s user=%s errors=%s",
            snapshot.app_key,
            snapshot.user_id,
            serializer.errors,
        )
        return JsonResponse(
            build_error_response(ErrorCode.INTERNAL_ERROR, "权限查询响应无法序列化。"),
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
        )

    _record_permission_query(principal=principal, snapshot=snapshot)
    return JsonResponse(serializer.data, status=HTTPStatus.OK)


def _authenticate_app(request: HttpRequest) -> AppPrincipal | JsonResponse:
    token = _permission_query_token_from_request(request)
    if token is None:
        return _authentication_failed_response()

    try:
        return authenticate_permission_query_token(token)
    except AuthenticationFailed:
        return _authentication_failed_response()
    except PermissionDenied:
        return _permission_denied_response()


def _permission_query_token_from_request(request: HttpRequest) -> str | None:
    raw_header: str | None = request.META.get("HTTP_AUTHORIZATION")
    if raw_header is None:
        return None
    scheme, separator, token = raw_header.partition(" ")
    if not separator:
        return None
    # RFC 7235 认证方案不区分大小写。
    if scheme.lower() != _AUTH_SCHEME.lower():
        return None
    if not token:
        return None
    return token


def _permission_query_expires_at(snapshot: PermissionSnapshot) -> datetime:
    ttl_expires_at = timezone.now() + timedelta(seconds=permission_query_ttl_seconds())
    grant_expires_at = snapshot.grant_expires_at
    if grant_expires_at is None:
        return ttl_expires_at
    return min(ttl_expires_at, grant_expires_at)


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
                "group_count": len(snapshot.groups),
                "grant_count": len(snapshot.grants),
                "grant_version": snapshot.grant_version,
                "catalog_version": snapshot.catalog_version,
                "snapshot_version": snapshot.snapshot_version,
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
