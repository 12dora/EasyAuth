from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final

from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from easyauth.api.errors import ErrorCode, JsonValue, build_error_response
from easyauth.api.pagination import pagination_item, total_pages
from easyauth.api.permission_query_auth import authenticate_permission_query_token
from easyauth.applications.models import App
from easyauth.config.rate_limit import client_ip, over_limit, rate_limit_exceeded
from easyauth.workflows.models import ApprovalInstance, ApprovalTemplate
from easyauth.workflows.services import (
    ApprovalCreateError,
    create_approval_instance,
    recover_stale_submission,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import QueryDict

    from easyauth.applications.services import AppPrincipal

_AUTH_SCHEME: Final = "Bearer"
_AUTHENTICATION_FAILED_MESSAGE: Final = "应用认证凭据无效。"
_PERMISSION_DENIED_MESSAGE: Final = "应用无权操作该资源。"
_TOO_MANY_REQUESTS_MESSAGE: Final = "请求过于频繁, 请稍后再试。"
_AUTH_FAIL_LIMIT: Final = 30
_AUTH_FAIL_WINDOW_SECONDS: Final = 300
_CREATE_RATE_LIMIT: Final = 60
_CREATE_RATE_WINDOW_SECONDS: Final = 60
_DEFAULT_PAGE: Final = 1
_DEFAULT_PAGE_SIZE: Final = 20
_MAX_PAGE: Final = 100_000
_MAX_PAGE_SIZE: Final = 100


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


@dataclass(frozen=True, slots=True)
class _PageRequest:
    page: int
    page_size: int

    @property
    def start(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def stop(self) -> int:
        return self.start + self.page_size


@csrf_exempt
def app_approval_instances(request: HttpRequest, app_key: str) -> JsonResponse:
    """下游应用审批实例集合: GET 列表 / POST 创建。"""
    match request.method:
        case "GET":
            return _list_approval_instances(request, app_key)
        case "POST":
            return _create_approval_instance(request, app_key)
        case _:
            return _error(
                ErrorCode.VALIDATION_ERROR,
                "请求方法无效。",
                HTTPStatus.METHOD_NOT_ALLOWED,
            )


@csrf_exempt
def app_approval_instance_detail(
    request: HttpRequest,
    app_key: str,
    instance_id: str,
) -> JsonResponse:
    """下游应用查询自身审批实例详情。"""
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


@csrf_exempt
def app_approval_templates(request: HttpRequest, app_key: str) -> JsonResponse:
    """列出本应用可用的活跃审批模板(含平台共用模板)。"""
    if request.method != "GET":
        return _error(ErrorCode.VALIDATION_ERROR, "请求方法无效。", HTTPStatus.METHOD_NOT_ALLOWED)
    match _authenticated_app(request, app_key):
        case App() as app:
            pass
        case JsonResponse() as response:
            return response
    templates = (
        ApprovalTemplate.objects.filter(is_active=True)
        .filter(Q(app=app) | Q(app__isnull=True))
        .order_by("key", "id")
    )
    items: list[JsonValue] = [_template_payload(template) for template in templates]
    return JsonResponse({"data": items})


def _create_approval_instance(request: HttpRequest, app_key: str) -> JsonResponse:
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


def _list_approval_instances(request: HttpRequest, app_key: str) -> JsonResponse:
    match _authenticated_app(request, app_key):
        case App() as app:
            pass
        case JsonResponse() as response:
            return response
    page = _page_request(request.GET)
    queryset = _filtered_instances(app, request.GET)
    total_items = queryset.count()
    rows = queryset[page.start : page.stop]
    items: list[JsonValue] = [
        _instance_payload(recover_stale_submission(instance)) for instance in rows
    ]
    return JsonResponse(
        {
            "data": items,
            "pagination": pagination_item(
                _PaginationView(
                    page=page.page,
                    page_size=page.page_size,
                    total_items=total_items,
                    total_pages=total_pages(
                        total_items=total_items,
                        page_size=page.page_size,
                    ),
                ),
            ),
        },
    )


@dataclass(frozen=True, slots=True)
class _PaginationView:
    page: int
    page_size: int
    total_items: int
    total_pages: int


def _filtered_instances(app: App, query: QueryDict) -> QuerySet[ApprovalInstance]:
    queryset = (
        ApprovalInstance.objects.select_related(
            "template",
            "originator_user",
            "completion_delivery",
        )
        .filter(app=app)
        .order_by("-created_at", "id")
    )
    status = query.get("status", "").strip()
    if status:
        queryset = queryset.filter(status=status)
    biz_key = query.get("biz_key", "").strip()
    if biz_key:
        queryset = queryset.filter(biz_key=biz_key)
    template_key = query.get("template_key", "").strip()
    if template_key:
        queryset = queryset.filter(template__key=template_key)
    return queryset


def _page_request(query: QueryDict) -> _PageRequest:
    return _PageRequest(
        page=_positive_integer(query.get("page"), default=_DEFAULT_PAGE, maximum=_MAX_PAGE),
        page_size=_positive_integer(
            query.get("page_size"),
            default=_DEFAULT_PAGE_SIZE,
            maximum=_MAX_PAGE_SIZE,
        ),
    )


def _positive_integer(value: str | None, *, default: int, maximum: int) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    if parsed < 1:
        return default
    return min(parsed, maximum)


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


def _template_payload(template: ApprovalTemplate) -> dict[str, JsonValue]:
    # 故意不暴露 dingtalk_process_code / form_mapping: 属于 provider 侧映射密钥。
    return {
        "key": template.key,
        "name": template.name,
        "form_schema": dict(template.form_schema),
        "is_active": template.is_active,
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
