from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from easyauth.api.errors import ErrorCode, JsonValue, build_error_response
from easyauth.api.permission_query_auth import authenticate_permission_query_token
from easyauth.applications.models import App
from easyauth.config.rate_limit import client_ip, over_limit, rate_limit_exceeded
from easyauth.workflows.models import ApprovalInstance
from easyauth.workflows.services import (
    ApprovalCreateError,
    create_approval_instance,
    recover_stale_submission,
)

if TYPE_CHECKING:
    from easyauth.applications.services import AppPrincipal

_AUTH_SCHEME: Final = "Bearer"
_AUTHENTICATION_FAILED_MESSAGE: Final = "应用认证凭据无效。"
_PERMISSION_DENIED_MESSAGE: Final = "应用无权操作该资源。"
_TOO_MANY_REQUESTS_MESSAGE: Final = "请求过于频繁, 请稍后再试。"
_AUTH_FAIL_LIMIT: Final = 30
_AUTH_FAIL_WINDOW_SECONDS: Final = 300
_CREATE_RATE_LIMIT: Final = 60
_CREATE_RATE_WINDOW_SECONDS: Final = 60


class _ApprovalCreatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    template_key: str = Field(min_length=1, max_length=64)
    originator_user_id: str = Field(min_length=1, max_length=128)
    form: dict[str, JsonValue] = Field(default_factory=dict)
    biz_key: str = Field(min_length=1, max_length=128)
    retry: bool = False


@csrf_exempt
def app_approval_instances(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method != "POST":
        return _error(ErrorCode.VALIDATION_ERROR, "请求方法无效。", HTTPStatus.METHOD_NOT_ALLOWED)
    match _authenticated_app(request, app_key):
        case App() as app:
            pass
        case JsonResponse() as response:
            return response
    try:
        payload = _ApprovalCreatePayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _error(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            HTTPStatus.UNPROCESSABLE_ENTITY,
            {"errors": str(exc)},
        )
    try:
        instance, created = create_approval_instance(
            app=app,
            template_key=payload.template_key,
            originator_user_id=payload.originator_user_id,
            form=dict(payload.form),
            biz_key=payload.biz_key,
            actor_id=app.app_key,
            retry_failed=payload.retry,
        )
    except ApprovalCreateError as exc:
        return _create_error_response(exc)
    status = HTTPStatus.CREATED if created else HTTPStatus.OK
    return JsonResponse(_instance_payload(instance), status=status)


@csrf_exempt
def app_approval_instance_detail(
    request: HttpRequest,
    app_key: str,
    instance_id: str,
) -> JsonResponse:
    if request.method != "GET":
        return _error(ErrorCode.VALIDATION_ERROR, "请求方法无效。", HTTPStatus.METHOD_NOT_ALLOWED)
    match _authenticated_app(request, app_key):
        case App() as app:
            pass
        case JsonResponse() as response:
            return response
    instance = (
        ApprovalInstance.objects.select_related(
            "template",
            "originator_user",
            "completion_delivery",
        )
        .filter(app=app, id=instance_id)
        .first()
    )
    if instance is None:
        return _error(ErrorCode.NOT_FOUND, "审批实例不存在。", HTTPStatus.NOT_FOUND)
    instance = recover_stale_submission(instance)
    return JsonResponse(_instance_payload(instance))


def _instance_payload(instance: ApprovalInstance) -> dict[str, JsonValue]:
    return {
        "instance_id": str(instance.id),
        "template_key": instance.template.key,
        "biz_key": instance.biz_key,
        "status": instance.status,
        "submission_state": instance.submission_state,
        "provider_correlation_key": str(instance.provider_correlation_key),
        "originator_user_id": instance.originator_user.authentik_user_id,
        "created_at": instance.created_at.isoformat(),
        "completed_at": (
            instance.completed_at.isoformat() if instance.completed_at is not None else None
        ),
    }


def _create_error_response(exc: ApprovalCreateError) -> JsonResponse:
    match exc.kind:
        case "template_not_found":
            return _error(ErrorCode.NOT_FOUND, exc.message, HTTPStatus.NOT_FOUND)
        case "dependency_unavailable":
            return _error(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                exc.message,
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        case "conflict":
            return _error(ErrorCode.SEMANTIC_VALIDATION_ERROR, exc.message, HTTPStatus.CONFLICT)
        case "originator_invalid" | "validation_error":
            return _error(
                ErrorCode.SEMANTIC_VALIDATION_ERROR,
                exc.message,
                HTTPStatus.UNPROCESSABLE_ENTITY,
            )


def _authenticated_app(request: HttpRequest, app_key: str) -> App | JsonResponse:
    # 与权限查询同一凭证体系: 认证失败按 IP 限流, 成功后按 app 限发起速率。
    ip = client_ip(request)
    if over_limit("approval-authfail", ip, limit=_AUTH_FAIL_LIMIT):
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
        "approval-create-rate",
        principal.credential_id,
        limit=_CREATE_RATE_LIMIT,
        window_seconds=_CREATE_RATE_WINDOW_SECONDS,
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


def _auth_failed(ip: str) -> JsonResponse:
    _ = rate_limit_exceeded(
        "approval-authfail",
        ip,
        limit=_AUTH_FAIL_LIMIT,
        window_seconds=_AUTH_FAIL_WINDOW_SECONDS,
    )
    return _error(
        ErrorCode.AUTHENTICATION_FAILED,
        _AUTHENTICATION_FAILED_MESSAGE,
        HTTPStatus.UNAUTHORIZED,
    )


def _bearer_token(request: HttpRequest) -> str | None:
    raw_header: str | None = request.META.get("HTTP_AUTHORIZATION")
    if raw_header is None:
        return None
    scheme, separator, token = raw_header.partition(" ")
    if not separator or scheme.lower() != _AUTH_SCHEME.lower() or not token:
        return None
    return token


def _error(
    code: ErrorCode,
    message: str,
    status: HTTPStatus,
    details: dict[str, JsonValue] | None = None,
) -> JsonResponse:
    return JsonResponse(build_error_response(code, message, details), status=status)
