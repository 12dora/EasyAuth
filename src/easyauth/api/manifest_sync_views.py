"""下游应用主动推送权限 manifest 的应用侧 API。

下游在部署/启动时携带自身静态 token 调用本端点, 即可把新增模块的权限模板
自动同步进 EasyAuth(版本单调递增 + content_hash 幂等, 与控制台自动接入同一套
判定逻辑)。区别于控制台自动接入: 应用必须已注册, 本端点不会创建新应用。
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from easyauth.api.errors import ErrorCode, JsonValue, build_error_response
from easyauth.api.permission_query_auth import authenticate_permission_query_token
from easyauth.applications.manifest_import import (
    ManifestVersionConflictError,
    sync_app_manifest,
)
from easyauth.applications.models import App
from easyauth.applications.permission_templates import PermissionTemplateImportError
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.config.net import InsecureUrlError, require_secure_url
from easyauth.config.rate_limit import client_ip, over_limit, rate_limit_exceeded

if TYPE_CHECKING:
    from easyauth.applications.services import AppPrincipal

_AUTH_SCHEME: Final = "Bearer"
_AUTHENTICATION_FAILED_MESSAGE: Final = "应用认证凭据无效。"
_PERMISSION_DENIED_MESSAGE: Final = "应用无权操作该资源。"
_TOO_MANY_REQUESTS_MESSAGE: Final = "请求过于频繁, 请稍后再试。"
_AUTH_FAIL_LIMIT: Final = 30
_AUTH_FAIL_WINDOW_SECONDS: Final = 300
_SYNC_RATE_LIMIT: Final = 10
_SYNC_RATE_WINDOW_SECONDS: Final = 60
_MANIFEST_MAX_BODY_BYTES: Final = 5 * 1024 * 1024


class _ManifestSyncPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    manifest: dict[str, JsonValue]
    # 下游对外基址: 用于把 manifest lifecycle 里的相对路径补全成 webhook 绝对地址。
    base_url: str | None = Field(default=None, max_length=512)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        if not normalized:
            return None
        from django.conf import settings

        try:
            require_secure_url(normalized, allow_local_http=settings.DEBUG)
        except InsecureUrlError as error:
            raise ValueError(str(error)) from error
        return normalized


@csrf_exempt
def app_manifest_sync(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method != "POST":
        return _error(ErrorCode.VALIDATION_ERROR, "请求方法无效。", HTTPStatus.METHOD_NOT_ALLOWED)
    match _authenticated_app(request, app_key):
        case App() as app:
            pass
        case JsonResponse() as response:
            return response
    if len(request.body) > _MANIFEST_MAX_BODY_BYTES:
        return _error(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            "manifest 超过大小限制。",
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        )
    try:
        payload = _ManifestSyncPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _error(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            HTTPStatus.UNPROCESSABLE_ENTITY,
            {"errors": str(exc)},
        )
    manifest_error = _validate_manifest_shape(payload.manifest, app_key)
    if manifest_error is not None:
        return manifest_error
    try:
        with transaction.atomic():
            outcome = sync_app_manifest(
                app=app,
                manifest=payload.manifest,
                actor_id=f"app:{app.app_key}",
                downstream_base_url=payload.base_url,
            )
    except ManifestVersionConflictError as exc:
        return _error(ErrorCode.CONFLICT, str(exc), HTTPStatus.CONFLICT)
    except PermissionTemplateImportError as exc:
        return _error(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            f"manifest 导入失败: {exc.message}",
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    app.refresh_from_db()
    _record_manifest_sync(app=app, outcome_up_to_date=outcome.already_up_to_date, version=outcome.template_version)
    return JsonResponse(
        {
            "app_key": app.app_key,
            "already_up_to_date": outcome.already_up_to_date,
            "template_version": outcome.template_version,
            "catalog_version": app.catalog_version,
        },
    )


def _validate_manifest_shape(manifest: dict[str, JsonValue], app_key: str) -> JsonResponse | None:
    manifest_app = manifest.get("app")
    if not isinstance(manifest_app, dict) or manifest_app.get("app_key") != app_key:
        return _error(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            "manifest.app.app_key 与请求不一致。",
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    schema_version = manifest.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version < 1:
        return _error(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            "manifest.schema_version 必须是 >=1 的整数。",
            HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    return None


def _authenticated_app(request: HttpRequest, app_key: str) -> App | JsonResponse:
    # 与权限查询/审批 API 同一凭证体系: 认证失败按 IP 限流, 成功后按凭证限速。
    ip = client_ip(request)
    if over_limit("manifest-sync-authfail", ip, limit=_AUTH_FAIL_LIMIT):
        return _error(ErrorCode.THROTTLED, _TOO_MANY_REQUESTS_MESSAGE, HTTPStatus.TOO_MANY_REQUESTS)
    token = _bearer_token(request)
    if token is None:
        return _auth_failed(ip)
    try:
        principal = authenticate_permission_query_token(token)
    except AuthenticationFailed:
        return _auth_failed(ip)
    except PermissionDenied:
        return _error(ErrorCode.PERMISSION_DENIED, _PERMISSION_DENIED_MESSAGE, HTTPStatus.FORBIDDEN)
    return _authorized_app(principal, app_key)


def _authorized_app(principal: AppPrincipal, app_key: str) -> App | JsonResponse:
    if principal.app_key != app_key:
        return _error(ErrorCode.PERMISSION_DENIED, _PERMISSION_DENIED_MESSAGE, HTTPStatus.FORBIDDEN)
    if rate_limit_exceeded(
        "manifest-sync-rate",
        principal.credential_id,
        limit=_SYNC_RATE_LIMIT,
        window_seconds=_SYNC_RATE_WINDOW_SECONDS,
    ):
        return _error(ErrorCode.THROTTLED, _TOO_MANY_REQUESTS_MESSAGE, HTTPStatus.TOO_MANY_REQUESTS)
    app = App.objects.filter(id=principal.app_id, is_active=True).first()
    if app is None:
        return _error(
            ErrorCode.AUTHENTICATION_FAILED,
            _AUTHENTICATION_FAILED_MESSAGE,
            HTTPStatus.UNAUTHORIZED,
        )
    return app


def _bearer_token(request: HttpRequest) -> str | None:
    raw_header: str | None = request.META.get("HTTP_AUTHORIZATION")
    if raw_header is None:
        return None
    scheme, separator, token = raw_header.partition(" ")
    if not separator or scheme.lower() != _AUTH_SCHEME.lower() or not token:
        return None
    return token


def _auth_failed(ip: str) -> JsonResponse:
    _ = rate_limit_exceeded(
        "manifest-sync-authfail",
        ip,
        limit=_AUTH_FAIL_LIMIT,
        window_seconds=_AUTH_FAIL_WINDOW_SECONDS,
    )
    return _error(
        ErrorCode.AUTHENTICATION_FAILED,
        _AUTHENTICATION_FAILED_MESSAGE,
        HTTPStatus.UNAUTHORIZED,
    )


def _record_manifest_sync(*, app: App, outcome_up_to_date: bool, version: int) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="app",
            actor_id=app.app_key,
            action="app_manifest_synced",
            target_type="app",
            target_id=app.app_key,
            metadata={
                "already_up_to_date": outcome_up_to_date,
                "template_version": version,
                "catalog_version": app.catalog_version,
            },
        ),
    )


def _error(
    code: ErrorCode,
    message: str,
    status: HTTPStatus,
    details: dict[str, JsonValue] | None = None,
) -> JsonResponse:
    return JsonResponse(build_error_response(code, message, details), status=status)
