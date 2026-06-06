from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from easyauth.api.authentication import AppBearerAuthentication
from easyauth.applications.services import AppPrincipal
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.query import PermissionSnapshot, resolve_user_permissions

if TYPE_CHECKING:
    from easyauth.applications.models import App
    from easyauth.audit.models import JsonValue


@dataclass(frozen=True, slots=True)
class PermissionQueryTestResult:
    status_code: int
    code: str
    explanation: str
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    version: int = 0
    expires_at: datetime | None = None


def run_permission_query_test(
    *,
    app: App,
    user_id: str,
    plaintext_token: str,
    actor_id: str,
) -> PermissionQueryTestResult:
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        result = PermissionQueryTestResult(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            code="validation_error",
            explanation="测试用户不能为空。",
        )
        _record_query_test(app=app, user_id=normalized_user_id, actor_id=actor_id, result=result)
        return result

    match _authenticate_token(plaintext_token):
        case AppPrincipal() as principal:
            pass
        case PermissionQueryTestResult() as error_result:
            _record_query_test(
                app=app,
                user_id=normalized_user_id,
                actor_id=actor_id,
                result=error_result,
            )
            return error_result

    if principal.app_key != app.app_key:
        result = PermissionQueryTestResult(
            status_code=HTTPStatus.FORBIDDEN,
            code="permission_denied",
            explanation="凭据绑定 App 与路径 app_key 不一致。",
        )
        _record_query_test(
            app=app,
            user_id=normalized_user_id,
            actor_id=actor_id,
            result=result,
            principal=principal,
        )
        return result

    try:
        snapshot = resolve_user_permissions(user=normalized_user_id, app=app)
    except ValidationError:
        result = PermissionQueryTestResult(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            code="internal_permission_query_error",
            explanation="权限查询内部错误, 请检查用户、授权、角色和权限配置。",
        )
        _record_query_test(
            app=app,
            user_id=normalized_user_id,
            actor_id=actor_id,
            result=result,
            principal=principal,
        )
        return result

    result = PermissionQueryTestResult(
        status_code=HTTPStatus.OK,
        code="ok",
        explanation=_success_explanation(snapshot),
        roles=snapshot.roles,
        permissions=snapshot.permissions,
        version=snapshot.version,
        expires_at=_expires_at(snapshot),
    )
    _record_query_test(
        app=app,
        user_id=normalized_user_id,
        actor_id=actor_id,
        result=result,
        principal=principal,
    )
    return result


def _authenticate_token(plaintext_token: str) -> AppPrincipal | PermissionQueryTestResult:
    request = HttpRequest()
    request.META["HTTP_AUTHORIZATION"] = f"Bearer {plaintext_token.strip()}"
    try:
        result = AppBearerAuthentication().authenticate(request)
    except AuthenticationFailed:
        return PermissionQueryTestResult(
            status_code=HTTPStatus.UNAUTHORIZED,
            code="authentication_failed",
            explanation="缺失或无效凭据。",
        )
    except PermissionDenied:
        return PermissionQueryTestResult(
            status_code=HTTPStatus.FORBIDDEN,
            code="permission_denied",
            explanation="App 已禁用。",
        )
    match result:
        case (AppPrincipal() as principal, None):
            return principal
        case None:
            return PermissionQueryTestResult(
                status_code=HTTPStatus.UNAUTHORIZED,
                code="authentication_failed",
                explanation="缺失或无效凭据。",
            )


def _success_explanation(snapshot: PermissionSnapshot) -> str:
    if not snapshot.roles and not snapshot.permissions:
        return "空权限响应。"
    return "权限查询成功。"


def _expires_at(snapshot: PermissionSnapshot) -> datetime:
    ttl_expires_at = timezone.now() + timedelta(seconds=_permission_query_ttl_seconds())
    grant_expires_at = snapshot.grant_expires_at
    if grant_expires_at is None:
        return ttl_expires_at
    return min(ttl_expires_at, grant_expires_at)


def _permission_query_ttl_seconds() -> int:
    value: int | bool | str = getattr(
        settings,
        "EASYAUTH_PERMISSION_QUERY_CACHE_TTL_SECONDS",
        300,
    )
    if isinstance(value, bool):
        return 300
    if isinstance(value, int):
        return value
    return 300


def _record_query_test(
    *,
    app: App,
    user_id: str,
    actor_id: str,
    result: PermissionQueryTestResult,
    principal: AppPrincipal | None = None,
) -> None:
    metadata: dict[str, JsonValue] = {
        "app_key": app.app_key,
        "user_id": user_id,
        "status_code": result.status_code,
        "code": result.code,
    }
    if principal is not None:
        metadata["credential_type"] = principal.credential_type
        metadata["credential_id"] = principal.credential_id
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=actor_id,
            action="permission_query_test_executed",
            target_type="app",
            target_id=str(app.id),
            metadata=metadata,
        ),
    )
