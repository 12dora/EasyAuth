from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import ClassVar, override

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.access_requests.models import AccessRequest
from easyauth.accounts.models import UserMirror
from easyauth.admin_console.api_payloads import list_payload, paginated_list_payload
from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.operation_filters import (
    Page,
    filter_access_grants,
    filter_access_requests,
    paginate_queryset,
)
from easyauth.admin_console.operations_audit import record_dependency_health_read
from easyauth.admin_console.operations_payloads import (
    access_request_dingtalk_fields,
    dependency_health_map_payload,
    health_item,
)
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.dependency_health import DependencyHealthService
from easyauth.applications.models import App
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.models import AccessGrant
from easyauth.grants.services import GrantService

type ConsoleApiResult = str | JsonResponse

USER_NOT_FOUND_MESSAGE = "用户不存在。"
APP_NOT_FOUND_MESSAGE = "应用不存在。"


@dataclass(frozen=True, slots=True)
class ConsoleOperationsSemanticError(Exception):
    message: str
    details: dict[str, JsonValue]

    @override
    def __str__(self) -> str:
        return self.message


class _EmergencyRevokePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    user_id: str = Field(min_length=1, max_length=128)
    app_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)


def operations_access_requests(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str():
            return _access_request_page_response(_access_request_page(request))
        case JsonResponse() as response:
            return response


def operations_access_grants(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str():
            return _access_grant_page_response(_access_grant_page(request))
        case JsonResponse() as response:
            return response


def operations_emergency_revokes(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
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
        result = _execute_emergency_revoke(request=request, actor_id=actor_id)
    except ValidationError as exc:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    except ConsoleOperationsSemanticError as exc:
        return _error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            str(exc),
            exc.details,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    _record_emergency_revoke(
        actor_id=actor_id,
        user_id=result.payload.user_id,
        app_key=result.payload.app_key,
        reason=result.payload.reason,
        revoked_count=result.revoked_count,
    )
    return _json_response(_emergency_revoke_response_payload(result))


@dataclass(frozen=True, slots=True)
class _EmergencyRevokeResult:
    payload: _EmergencyRevokePayload
    revoked_count: int


def _execute_emergency_revoke(
    *,
    request: HttpRequest,
    actor_id: str,
) -> _EmergencyRevokeResult:
    payload = _EmergencyRevokePayload.model_validate_json(request.body)
    user = _user_for_id(payload.user_id)
    app = _app_for_key(payload.app_key)
    revoked_grant = GrantService.revoke_grant(
        user=user,
        app=app,
        actor_type="admin",
        actor_id=actor_id,
        reason=payload.reason,
    )
    revoked_count = 0 if revoked_grant is None else 1
    return _EmergencyRevokeResult(payload=payload, revoked_count=revoked_count)


def _emergency_revoke_response_payload(
    result: _EmergencyRevokeResult,
) -> dict[str, JsonValue]:
    return {
        "status": "accepted",
        "revoked_count": result.revoked_count,
        "user_id": result.payload.user_id,
        "app_key": result.payload.app_key,
    }


def operations_dependency_health(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            record_dependency_health_read(actor_id)
            items = DependencyHealthService.latest_items()
            result: list[JsonValue] = []
            result.extend(health_item(item) for item in items)
            payload = list_payload(result)
            payload.update(dependency_health_map_payload(items))
            return _json_response(payload)
        case JsonResponse() as response:
            return response


def _access_request_page(request: HttpRequest) -> Page[AccessRequest]:
    queryset = AccessRequest.objects.select_related("user", "app").all()
    return paginate_queryset(filter_access_requests(queryset, request.GET), request.GET)


def _access_grant_page(request: HttpRequest) -> Page[AccessGrant]:
    queryset = AccessGrant.objects.select_related("user", "app").all()
    return paginate_queryset(filter_access_grants(queryset, request.GET), request.GET)


def _access_request_item(access_request: AccessRequest) -> dict[str, JsonValue]:
    return {
        "id": access_request.id,
        "user_id": access_request.user.authentik_user_id,
        "app_key": access_request.app.app_key,
        "status": access_request.status,
        "request_type": access_request.request_type,
        "grant_type": access_request.grant_type,
        "reason": access_request.reason,
        "submitted_at": access_request.submitted_at.isoformat(),
        **access_request_dingtalk_fields(access_request),
    }


def _access_grant_item(access_grant: AccessGrant) -> dict[str, JsonValue]:
    return {
        "id": access_grant.id,
        "user_id": access_grant.user.authentik_user_id,
        "app_key": access_grant.app.app_key,
        "status": access_grant.status,
        "grant_type": access_grant.grant_type,
        "version": access_grant.version,
        "is_current": access_grant.is_current,
        "grant_expires_at": datetime_value(access_grant.grant_expires_at),
    }


def _user_for_id(user_id: str) -> UserMirror:
    user = UserMirror.objects.filter(authentik_user_id=user_id).first()
    if user is None:
        raise ConsoleOperationsSemanticError(USER_NOT_FOUND_MESSAGE, {"user_id": user_id})
    return user


def _app_for_key(app_key: str) -> App:
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        raise ConsoleOperationsSemanticError(APP_NOT_FOUND_MESSAGE, {"app_key": app_key})
    return app


def _record_emergency_revoke(
    *,
    actor_id: str,
    user_id: str,
    app_key: str,
    reason: str,
    revoked_count: int,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor_id,
            action="emergency_revoke_applied",
            target_type="user_app",
            target_id=f"{user_id}:{app_key}",
            metadata={
                "user_id": user_id,
                "app_key": app_key,
                "reason": reason,
                "revoked_count": revoked_count,
            },
        ),
    )


def _access_request_page_response(page: Page[AccessRequest]) -> JsonResponse:
    result: list[JsonValue] = []
    result.extend(_access_request_item(access_request) for access_request in page.items)
    return _json_response(
        paginated_list_payload(items=result, pagination=_pagination_item(page)),
    )


def _access_grant_page_response(page: Page[AccessGrant]) -> JsonResponse:
    result: list[JsonValue] = []
    result.extend(_access_grant_item(access_grant) for access_grant in page.items)
    return _json_response(
        paginated_list_payload(items=result, pagination=_pagination_item(page)),
    )


def _pagination_item(page: Page[AccessRequest] | Page[AccessGrant]) -> dict[str, JsonValue]:
    return {
        "page": page.page,
        "page_size": page.page_size,
        "total_items": page.total_items,
        "total_pages": page.total_pages,
    }
