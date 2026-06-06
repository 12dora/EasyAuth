from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import ClassVar, override

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.access_requests.application_grants import (
    GrantApplyFailureError,
    apply_grant_fact,
)
from easyauth.access_requests.models import (
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_TYPE_GRANT,
    AccessRequest,
)
from easyauth.api.errors import ErrorCode, ErrorResponse, JsonValue, build_error_response
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.models import AccessGrant
from easyauth.grants.operations import current_grant

type ConsoleApiResult = str | JsonResponse

REQUEST_NOT_FOUND_MESSAGE = "申请不存在。"
REQUEST_NOT_RETRYABLE_MESSAGE = "该申请当前不可重试。"
REQUEST_GRANT_RETRY_FAILED_MESSAGE = "授权重试失败。"
REQUEST_CURRENT_GRANT_EXISTS_MESSAGE = "目标用户已存在当前授权, 不能重试创建授权。"


@dataclass(frozen=True, slots=True)
class RetryGrantSemanticError(Exception):
    message: str
    details: dict[str, JsonValue]

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class _RetryGrantApplication:
    actor_type: str
    actor_id: str
    reason: str


class _RetryGrantPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    reason: str = Field(min_length=1, max_length=1000)


def operations_retry_grant(request: HttpRequest, request_id: int) -> JsonResponse:
    match _require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求方法无效。",
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )
    try:
        payload = _RetryGrantPayload.model_validate_json(request.body)
        grant = _retry_grant(request_id=request_id, actor_id=actor_id, reason=payload.reason)
    except ValidationError as exc:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    except RetryGrantSemanticError as exc:
        return _error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            str(exc),
            exc.details,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    return _json_response(
        {
            "request_id": request_id,
            "grant_id": grant.id,
            "version": grant.version,
            "status": "grant_applied",
        },
    )


@transaction.atomic
def _retry_grant(*, request_id: int, actor_id: str, reason: str) -> AccessGrant:
    access_request = _retryable_access_request(request_id)
    match access_request.status:
        case "grant_applied":
            return _applied_grant(access_request)
        case "grant_failed":
            pass
        case status:
            raise RetryGrantSemanticError(
                REQUEST_NOT_RETRYABLE_MESSAGE,
                {"request_id": request_id, "status": status},
            )
    if access_request.request_type == REQUEST_TYPE_GRANT:
        _ensure_no_current_grant(access_request)
    try:
        grant = apply_grant_fact(
            access_request,
            _RetryGrantApplication(actor_type="admin", actor_id=actor_id, reason=reason),
        )
    except (DjangoValidationError, IntegrityError, GrantApplyFailureError) as exc:
        raise RetryGrantSemanticError(
            REQUEST_GRANT_RETRY_FAILED_MESSAGE,
            {"request_id": request_id, "error": str(exc)},
        ) from exc
    access_request.status = REQUEST_STATUS_GRANT_APPLIED
    access_request.applied_at = timezone.now()
    access_request.full_clean()
    access_request.save(update_fields=["status", "applied_at"])
    _record_retry_event(
        access_request=access_request,
        grant=grant,
        actor_id=actor_id,
        reason=reason,
    )
    return grant


def _applied_grant(access_request: AccessRequest) -> AccessGrant:
    grant = (
        AccessGrant.objects.select_for_update()
        .filter(user=access_request.user, app=access_request.app)
        .order_by("-version", "-id")
        .first()
    )
    if grant is None:
        raise RetryGrantSemanticError(
            REQUEST_NOT_RETRYABLE_MESSAGE,
            {"request_id": access_request.id, "status": access_request.status},
        )
    return grant


def _retryable_access_request(request_id: int) -> AccessRequest:
    access_request = (
        AccessRequest.objects.select_for_update()
        .select_related("user", "app")
        .filter(id=request_id)
        .first()
    )
    if access_request is None:
        raise RetryGrantSemanticError(REQUEST_NOT_FOUND_MESSAGE, {"request_id": request_id})
    match access_request.status:
        case "grant_failed" | "grant_applied":
            pass
        case status:
            raise RetryGrantSemanticError(
                REQUEST_NOT_RETRYABLE_MESSAGE,
                {"request_id": request_id, "status": status},
            )
    return access_request


def _ensure_no_current_grant(access_request: AccessRequest) -> None:
    existing_grant = current_grant(access_request.user, access_request.app)
    if existing_grant is None:
        return
    raise RetryGrantSemanticError(
        REQUEST_CURRENT_GRANT_EXISTS_MESSAGE,
        {
            "request_id": access_request.id,
            "user_id": access_request.user.authentik_user_id,
            "app_key": access_request.app.app_key,
            "grant_id": existing_grant.id,
            "version": existing_grant.version,
        },
    )


def _record_retry_event(
    *,
    access_request: AccessRequest,
    grant: AccessGrant,
    actor_id: str,
    reason: str,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor_id,
            action="access_request_grant_retry_applied",
            target_type="access_request",
            target_id=str(access_request.id),
            metadata={
                "user_id": access_request.user.authentik_user_id,
                "app_key": access_request.app.app_key,
                "grant_id": grant.id,
                "version": grant.version,
                "reason": reason,
            },
        ),
    )


def _require_superuser(request: HttpRequest) -> ConsoleApiResult:
    user = request.user
    if not user.is_authenticated:
        return _error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            "控制台登录已失效。",
            status=HTTPStatus.UNAUTHORIZED,
        )
    if not bool(getattr(user, "is_superuser", False)):
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有系统管理员可以执行该操作。",
            status=HTTPStatus.FORBIDDEN,
        )
    return user.get_username()


def _error_response(
    code: ErrorCode,
    message: str,
    details: dict[str, JsonValue] | None = None,
    *,
    status: HTTPStatus,
) -> JsonResponse:
    return _json_response(build_error_response(code, message, details), status=status)


def _json_response(
    payload: dict[str, JsonValue] | ErrorResponse,
    *,
    status: HTTPStatus = HTTPStatus.OK,
) -> JsonResponse:
    return JsonResponse(
        payload,
        status=status,
        json_dumps_params={"ensure_ascii": False},
    )
