from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from easyauth.api.permission_query_auth import (
    authenticate_permission_query_token,
    permission_query_ttl_seconds,
)
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.managed_users import ManagedUsersResolutionUnavailableError
from easyauth.grants.query import (
    ExpandedGrant,
    GroupSnapshot,
    PermissionSnapshot,
    resolve_user_permissions,
)

if TYPE_CHECKING:
    from easyauth.applications.models import App
    from easyauth.applications.services import AppPrincipal
    from easyauth.audit.models import JsonValue


@dataclass(frozen=True, slots=True)
class PermissionQueryTestResult:
    status_code: int
    code: str
    explanation: str
    groups: tuple[GroupSnapshot, ...] = ()
    grants: tuple[ExpandedGrant, ...] = ()
    grant_version: int = 0
    catalog_version: int = 0
    snapshot_version: str = "0.0"
    expires_at: datetime | None = None


def run_permission_query_test(
    *, app: App, user_id: str, plaintext_token: str, actor_id: str
) -> PermissionQueryTestResult:
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        result = PermissionQueryTestResult(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            code="validation_error",
            explanation="测试用户不能为空。",
        )
        return _record_query_test_result(
            app=app, user_id=normalized_user_id, actor_id=actor_id, result=result
        )

    auth_result = _authenticate_token(plaintext_token)
    if isinstance(auth_result, PermissionQueryTestResult):
        return _record_query_test_result(
            app=app,
            user_id=normalized_user_id,
            actor_id=actor_id,
            result=auth_result,
        )

    principal = auth_result
    app_error = _validate_principal_app(app=app, principal=principal)
    if app_error is not None:
        return _record_query_test_result(
            app=app,
            user_id=normalized_user_id,
            actor_id=actor_id,
            result=app_error,
            principal=principal,
        )

    result = _resolve_snapshot_result(app=app, user_id=normalized_user_id)
    return _record_query_test_result(
        app=app, user_id=normalized_user_id, actor_id=actor_id, result=result, principal=principal
    )


def _record_query_test_result(
    *,
    app: App,
    user_id: str,
    actor_id: str,
    result: PermissionQueryTestResult,
    principal: AppPrincipal | None = None,
) -> PermissionQueryTestResult:
    _record_query_test(
        app=app,
        user_id=user_id,
        actor_id=actor_id,
        result=result,
        principal=principal,
    )
    return result


def _query_test_auth_error_result(
    *,
    status_code: int,
    code: str,
    explanation: str,
) -> PermissionQueryTestResult:
    return PermissionQueryTestResult(
        status_code=status_code,
        code=code,
        explanation=explanation,
    )


def _validate_principal_app(
    *,
    app: App,
    principal: AppPrincipal,
) -> PermissionQueryTestResult | None:
    if principal.app_key == app.app_key:
        return None
    return PermissionQueryTestResult(
        status_code=HTTPStatus.FORBIDDEN,
        code="permission_denied",
        explanation="凭据绑定 App 与路径 app_key 不一致。",
    )


def _resolve_snapshot_result(
    *,
    app: App,
    user_id: str,
) -> PermissionQueryTestResult:
    try:
        snapshot = resolve_user_permissions(user=user_id, app=app)
    except ValidationError:
        return PermissionQueryTestResult(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            code="internal_permission_query_error",
            explanation="权限查询内部错误, 请检查用户、授权、角色和权限配置。",
        )
    except ManagedUsersResolutionUnavailableError:
        return PermissionQueryTestResult(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            code="managed_scope_directory_unavailable",
            explanation="MANAGED_USERS 解析依赖的组织目录暂不可用, 请稍后重试。",
        )

    return PermissionQueryTestResult(
        status_code=HTTPStatus.OK,
        code="ok",
        explanation=_success_explanation(snapshot),
        groups=snapshot.groups,
        grants=snapshot.grants,
        grant_version=snapshot.grant_version,
        catalog_version=snapshot.catalog_version,
        snapshot_version=snapshot.snapshot_version,
        expires_at=_expires_at(snapshot),
    )


def _authenticate_token(plaintext_token: str) -> AppPrincipal | PermissionQueryTestResult:
    try:
        return authenticate_permission_query_token(plaintext_token)
    except AuthenticationFailed:
        return _query_test_auth_error_result(
            status_code=HTTPStatus.UNAUTHORIZED,
            code="authentication_failed",
            explanation="缺失或无效凭据。",
        )
    except PermissionDenied:
        return _query_test_auth_error_result(
            status_code=HTTPStatus.FORBIDDEN,
            code="permission_denied",
            explanation="App 已禁用。",
        )


def _success_explanation(snapshot: PermissionSnapshot) -> str:
    if not snapshot.groups and not snapshot.grants:
        return "空权限响应。"
    return "权限查询成功。"


def _expires_at(snapshot: PermissionSnapshot) -> datetime:
    ttl_expires_at = timezone.now() + timedelta(seconds=permission_query_ttl_seconds())
    membership_expirations = [
        item.expires_at
        for item in (*snapshot.groups, *snapshot.grants)
        if item.expires_at is not None
    ]
    if not membership_expirations:
        return ttl_expires_at
    return min(ttl_expires_at, *membership_expirations)


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
    if result.status_code == HTTPStatus.OK:
        metadata["group_count"] = len(result.groups)
        metadata["grant_count"] = len(result.grants)
        metadata["grant_version"] = result.grant_version
        metadata["catalog_version"] = result.catalog_version
        metadata["snapshot_version"] = result.snapshot_version
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
