from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, TypedDict, cast

from django.core.cache import cache
from django.db import connection
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from easyauth.accounts.directory_snapshot import build_directory_snapshot
from easyauth.accounts.models import DingTalkDepartmentMirror, DingTalkUserMirror, UserMirror
from easyauth.api.directory_payloads import (
    DINGTALK_STATUS_ACTIVE,
    build_manager_full_item,
    build_user_detail,
    build_user_list_items,
    department_item,
    parse_user_ref,
    removed_directory_user_item,
    resolve_dingtalk_user,
    resolve_user_mirror,
)
from easyauth.api.errors import ErrorCode, JsonValue, build_error_response
from easyauth.api.pagination import Pagination, pagination_item, total_pages
from easyauth.api.permission_query_auth import authenticate_permission_query_token
from easyauth.api.responses import json_response
from easyauth.applications.capabilities import (
    app_capability_enabled,
    credential_capability_enabled,
)
from easyauth.applications.models import CAPABILITY_DIRECTORY, App
from easyauth.applications.services import AppPrincipal
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.config.rate_limit import client_ip, over_limit, rate_limit_exceeded

if TYPE_CHECKING:
    from django.db.models import QuerySet

_AUTHENTICATION_FAILED_MESSAGE: Final = "应用认证凭据无效。"
_PERMISSION_DENIED_MESSAGE: Final = "应用无权查询该资源。"
_DIRECTORY_CAPABILITY_DENIED_MESSAGE: Final = "应用未开通目录能力。"
_TOO_MANY_REQUESTS_MESSAGE: Final = "请求过于频繁, 请稍后再试。"
_USER_NOT_FOUND_MESSAGE: Final = "用户不存在。"
_NO_MANAGER_MESSAGE: Final = "用户没有直接主管。"
_SNAPSHOT_CONFLICT_MESSAGE: Final = "目录快照已变化, 请从第一页重新读取。"
_AUTH_SCHEME: Final = "Bearer"
_AUTH_FAIL_LIMIT: Final = 30
_AUTH_FAIL_WINDOW_SECONDS: Final = 300
_QUERY_RATE_LIMIT: Final = 240
_QUERY_RATE_WINDOW_SECONDS: Final = 60
_RETRY_AFTER_HEADER: Final = "Retry-After"
_CACHE_CONTROL_HEADER: Final = "Cache-Control"
_CACHE_CONTROL_VALUE: Final = "private, max-age=60"
_DEFAULT_PAGE: Final = 1
_DEFAULT_PAGE_SIZE: Final = 20
_MAX_PAGE: Final = 100_000
_MAX_USERS_PAGE_SIZE: Final = 200
_DIRECTORY_AUDIT_ACTION: Final = "app_directory_queried"
_DIRECTORY_AUDIT_TARGET_TYPE: Final = "directory"
_LIST_AUDIT_TTL_SECONDS: Final = 3700
_AUTH_FAIL_NAMESPACE: Final = "directory-authfail"
_RATE_NAMESPACE: Final = "directory-rate"


class _ListAuditState(TypedDict):
    hour_bucket: str
    call_count: int
    q_present: bool
    result_count: int
    credential_id: str | int


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


@dataclass(frozen=True, slots=True)
class _PaginationView:
    page: int
    page_size: int
    total_items: int
    total_pages: int


@require_http_methods(["GET"])
def directory_users(request: HttpRequest, app_key: str) -> JsonResponse:
    match _authenticate_capability_and_throttle(request, app_key):
        case AppPrincipal() as principal:
            pass
        case JsonResponse() as response:
            return response

    snapshot_before = build_directory_snapshot()
    requested_snapshot_id = request.GET.get("snapshot_id", "").strip()
    current_snapshot_id = cast("str", snapshot_before["snapshot_id"])
    if requested_snapshot_id and requested_snapshot_id != current_snapshot_id:
        return _snapshot_conflict_response(
            reason="snapshot_mismatch",
            expected_snapshot_id=requested_snapshot_id,
            actual_snapshot_id=current_snapshot_id,
        )

    page = _page_request(request, max_page_size=_MAX_USERS_PAGE_SIZE)
    queryset = _filtered_users(request)
    total_items = queryset.count()
    rows = list(queryset[page.start : page.stop])
    data_items: list[JsonValue] = build_user_list_items(rows)
    pagination = pagination_item(
        cast(
            "Pagination",
            cast(
                "object",
                _PaginationView(
                    page=page.page,
                    page_size=page.page_size,
                    total_items=total_items,
                    total_pages=total_pages(total_items=total_items, page_size=page.page_size),
                ),
            ),
        ),
    )
    payload: dict[str, JsonValue] = {
        "data": data_items,
        "pagination": pagination,
    }
    snapshot_after = build_directory_snapshot()
    final_snapshot_id = cast("str", snapshot_after["snapshot_id"])
    if final_snapshot_id != current_snapshot_id:
        return _snapshot_conflict_response(
            reason="snapshot_changed",
            expected_snapshot_id=current_snapshot_id,
            actual_snapshot_id=final_snapshot_id,
        )
    _record_directory_audit(
        principal=principal,
        endpoint="users",
        result_count=len(rows),
        q_present=bool(request.GET.get("q", "").strip()),
        aggregated=True,
    )
    return _directory_response(payload, directory_snapshot=snapshot_after)


@require_http_methods(["GET"])
def directory_user_detail(request: HttpRequest, app_key: str, user_ref: str) -> JsonResponse:
    match _authenticate_capability_and_throttle(request, app_key):
        case AppPrincipal() as principal:
            pass
        case JsonResponse() as response:
            return response

    detail = _resolve_user_detail(user_ref)
    if detail is None:
        return _not_found_response(_USER_NOT_FOUND_MESSAGE, reason="user_not_found")
    _record_directory_audit(
        principal=principal,
        endpoint="user_detail",
        result_count=1,
        q_present=False,
        aggregated=False,
    )
    return _directory_response(detail)


@require_http_methods(["GET"])
def directory_user_manager(request: HttpRequest, app_key: str, user_ref: str) -> JsonResponse:
    match _authenticate_capability_and_throttle(request, app_key):
        case AppPrincipal() as principal:
            pass
        case JsonResponse() as response:
            return response

    subject = _resolve_subject(user_ref)
    if subject is None:
        return _not_found_response(_USER_NOT_FOUND_MESSAGE, reason="user_not_found")
    manager = _resolve_manager(subject)
    if manager is None:
        return _not_found_response(_NO_MANAGER_MESSAGE, reason="no_manager")
    payload = build_manager_full_item(manager)
    _record_directory_audit(
        principal=principal,
        endpoint="user_manager",
        result_count=1,
        q_present=False,
        aggregated=False,
    )
    return _directory_response(payload)


@require_http_methods(["GET"])
def directory_user_subordinates(
    request: HttpRequest,
    app_key: str,
    user_ref: str,
) -> JsonResponse:
    match _authenticate_capability_and_throttle(request, app_key):
        case AppPrincipal() as principal:
            pass
        case JsonResponse() as response:
            return response

    subject = _resolve_subject(user_ref)
    if subject is None:
        return _not_found_response(_USER_NOT_FOUND_MESSAGE, reason="user_not_found")
    manager_dingtalk_id = _subject_dingtalk_user_id(subject)
    if not manager_dingtalk_id:
        items: list[JsonValue] = []
    else:
        rows = list(
            DingTalkUserMirror.objects.filter(
                manager_userid=manager_dingtalk_id,
                status=DINGTALK_STATUS_ACTIVE,
            ).order_by("name", "user_id"),
        )
        items = build_user_list_items(rows)
    payload: dict[str, JsonValue] = {"data": items}
    _record_directory_audit(
        principal=principal,
        endpoint="user_subordinates",
        result_count=len(items),
        q_present=False,
        aggregated=False,
    )
    return _directory_response(payload)


@require_http_methods(["GET"])
def directory_departments(request: HttpRequest, app_key: str) -> JsonResponse:
    match _authenticate_capability_and_throttle(request, app_key):
        case AppPrincipal() as principal:
            pass
        case JsonResponse() as response:
            return response

    queryset = DingTalkDepartmentMirror.objects.order_by("order", "dept_id")
    if "parent_id" in request.GET:
        queryset = queryset.filter(parent_id=request.GET.get("parent_id", ""))
    rows = list(queryset)
    department_items: list[JsonValue] = [department_item(row) for row in rows]
    payload: dict[str, JsonValue] = {"data": department_items}
    _record_directory_audit(
        principal=principal,
        endpoint="departments",
        result_count=len(rows),
        q_present=False,
        aggregated=True,
    )
    return _directory_response(payload)


def _authenticate_capability_and_throttle(
    request: HttpRequest,
    app_key: str,
) -> AppPrincipal | JsonResponse:
    match _authenticate_and_throttle(request):
        case AppPrincipal() as principal:
            pass
        case JsonResponse() as response:
            return response
    if principal.app_key != app_key:
        return _permission_denied_response(_PERMISSION_DENIED_MESSAGE)
    app = App.objects.filter(id=principal.app_id).first()
    if app is None:
        return _authentication_failed_response()
    if not app_capability_enabled(
        app.id,
        CAPABILITY_DIRECTORY,
    ) or not credential_capability_enabled(principal, CAPABILITY_DIRECTORY):
        return _permission_denied_response(_DIRECTORY_CAPABILITY_DENIED_MESSAGE)
    return principal


def _authenticate_and_throttle(request: HttpRequest) -> AppPrincipal | JsonResponse:
    # 认证失败按 IP 限流, 认证成功后按 credential 限请求速率(纵深防御)。
    ip = client_ip(request)
    if over_limit(_AUTH_FAIL_NAMESPACE, ip, limit=_AUTH_FAIL_LIMIT):
        return _too_many_requests_response(_AUTH_FAIL_WINDOW_SECONDS)
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
        return _too_many_requests_response(_QUERY_RATE_WINDOW_SECONDS)
    return principal


def _authenticate_app(request: HttpRequest) -> AppPrincipal | JsonResponse:
    token = _bearer_token_from_request(request)
    if token is None:
        return _authentication_failed_response()
    try:
        return authenticate_permission_query_token(token)
    except AuthenticationFailed:
        return _authentication_failed_response()
    except PermissionDenied:
        return _permission_denied_response(_PERMISSION_DENIED_MESSAGE)


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


def _filtered_users(request: HttpRequest) -> QuerySet[DingTalkUserMirror]:
    queryset = DingTalkUserMirror.objects.all()
    include_inactive = request.GET.get("include_inactive", "").strip().lower() == "true"
    if not include_inactive:
        queryset = queryset.filter(status=DINGTALK_STATUS_ACTIVE)
    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(
            Q(name__icontains=query) | Q(title__icontains=query) | Q(user_id__icontains=query),
        )
    department_id = request.GET.get("department_id", "").strip()
    if department_id:
        queryset = _filter_by_department(queryset, department_id)
    manager_id = request.GET.get("manager_id", "").strip()
    if manager_id:
        manager_dingtalk_id = _resolve_manager_filter_id(manager_id)
        if manager_dingtalk_id is None:
            return DingTalkUserMirror.objects.none()
        queryset = queryset.filter(manager_userid=manager_dingtalk_id)
    return queryset.order_by("name", "user_id")


def _filter_by_department(
    queryset: QuerySet[DingTalkUserMirror],
    department_id: str,
) -> QuerySet[DingTalkUserMirror]:
    # 直接成员(不递归)。PostgreSQL 用 JSON 数组 contains; SQLite 测试库无此 lookup,
    # 退化为带引号子串匹配(镜像里 department_ids 存字符串数组, 语义一致)。
    if connection.features.supports_json_field_contains:
        return queryset.filter(department_ids__contains=[department_id])
    return queryset.filter(department_ids__icontains=f'"{department_id}"')


def _resolve_manager_filter_id(manager_id: str) -> str | None:
    kind, identifier = parse_user_ref(manager_id)
    if not identifier:
        return None
    if kind == "dingtalk":
        exists = DingTalkUserMirror.objects.filter(user_id=identifier).exists()
        return identifier if exists else None
    user = UserMirror.objects.filter(authentik_user_id=identifier).first()
    if user is None or not user.dingtalk_userid:
        return None
    return user.dingtalk_userid


def _resolve_user_detail(user_ref: str) -> dict[str, JsonValue] | None:
    dingtalk_user = resolve_dingtalk_user(user_ref)
    if dingtalk_user is not None:
        return build_user_detail(dingtalk_user)
    # 边界: 曾登录但钉钉目录已无此人 → 详情仍可查(与 D3/D4 subject 解析口径一致,
    # authentik / dt: 两种引用均可落到 UserMirror)。
    user = resolve_user_mirror(user_ref)
    if user is None:
        return None
    return removed_directory_user_item(user)


@dataclass(frozen=True, slots=True)
class _Subject:
    dingtalk_user: DingTalkUserMirror | None
    user_mirror: UserMirror | None


def _resolve_subject(user_ref: str) -> _Subject | None:
    dingtalk_user = resolve_dingtalk_user(user_ref)
    if dingtalk_user is not None:
        return _Subject(dingtalk_user=dingtalk_user, user_mirror=None)
    user = resolve_user_mirror(user_ref)
    if user is not None:
        return _Subject(dingtalk_user=None, user_mirror=user)
    return None


def _subject_dingtalk_user_id(subject: _Subject) -> str:
    if subject.dingtalk_user is not None:
        return subject.dingtalk_user.user_id
    if subject.user_mirror is not None:
        return subject.user_mirror.dingtalk_userid
    return ""


def _resolve_manager(subject: _Subject) -> DingTalkUserMirror | None:
    if subject.dingtalk_user is not None:
        manager_userid = (subject.dingtalk_user.manager_userid or "").strip()
        if not manager_userid:
            return None
        return (
            DingTalkUserMirror.objects.filter(
                corp_id=subject.dingtalk_user.corp_id,
                user_id=manager_userid,
            )
            .order_by("source_slug")
            .first()
        )
    if subject.user_mirror is None:
        return None
    manager_userid = (subject.user_mirror.manager_userid or "").strip()
    if not manager_userid:
        return None
    return (
        DingTalkUserMirror.objects.filter(
            corp_id=subject.user_mirror.dingtalk_corp_id,
            user_id=manager_userid,
        )
        .order_by("source_slug")
        .first()
    )


def _page_request(request: HttpRequest, *, max_page_size: int) -> _PageRequest:
    return _PageRequest(
        page=_positive_integer(
            request.GET.get("page"),
            default=_DEFAULT_PAGE,
            maximum=_MAX_PAGE,
        ),
        page_size=_positive_integer(
            request.GET.get("page_size"),
            default=_DEFAULT_PAGE_SIZE,
            maximum=max_page_size,
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


def _record_directory_audit(
    *,
    principal: AppPrincipal,
    endpoint: str,
    result_count: int,
    q_present: bool,
    aggregated: bool,
) -> None:
    if aggregated:
        _record_aggregated_list_audit(
            principal=principal,
            endpoint=endpoint,
            result_count=result_count,
            q_present=q_present,
        )
        return
    _ = AuditService.record(
        AuditRecord(
            actor_type="app",
            actor_id=principal.app_key,
            action=_DIRECTORY_AUDIT_ACTION,
            target_type=_DIRECTORY_AUDIT_TARGET_TYPE,
            target_id=principal.app_key,
            metadata={
                "endpoint": endpoint,
                "q_present": q_present,
                "result_count": result_count,
                "credential_id": principal.credential_id,
            },
        ),
    )


def _record_aggregated_list_audit(
    *,
    principal: AppPrincipal,
    endpoint: str,
    result_count: int,
    q_present: bool,
) -> None:
    # list 搜索类按 app x 端点 x 小时聚合: 小时内只做 cache 计数,
    # 小时翻转时把上一小时累计 call_count 落库一条(AuditLog 只追加不可更新)。
    hour_bucket = timezone.now().strftime("%Y%m%d%H")
    state_key = f"easyauth:directory-audit:{principal.app_key}:{endpoint}"
    raw_state = cast("object | None", cache.get(state_key))
    state = _as_audit_state(raw_state)
    if state is not None and state["hour_bucket"] != hour_bucket:
        _flush_aggregated_list_audit(principal=principal, endpoint=endpoint, state=state)
        state = None
    if state is None:
        next_state: _ListAuditState = {
            "hour_bucket": hour_bucket,
            "call_count": 1,
            "q_present": q_present,
            "result_count": result_count,
            "credential_id": principal.credential_id,
        }
        cache.set(state_key, next_state, _LIST_AUDIT_TTL_SECONDS)
        return
    next_state = {
        "hour_bucket": hour_bucket,
        "call_count": state["call_count"] + 1,
        "q_present": state["q_present"] or q_present,
        "result_count": result_count,
        "credential_id": principal.credential_id,
    }
    cache.set(state_key, next_state, _LIST_AUDIT_TTL_SECONDS)


def _as_audit_state(raw: object | None) -> _ListAuditState | None:
    if not isinstance(raw, dict):
        return None
    mapping = cast("dict[str, object]", raw)
    hour_bucket = mapping.get("hour_bucket")
    call_count = mapping.get("call_count")
    if not isinstance(hour_bucket, str) or not isinstance(call_count, int):
        return None
    q_present_raw = mapping.get("q_present", False)
    result_count_raw = mapping.get("result_count", 0)
    credential_id_raw = mapping.get("credential_id", "")
    result_count = result_count_raw if isinstance(result_count_raw, int) else 0
    if isinstance(credential_id_raw, (str, int)):
        credential_id: str | int = credential_id_raw
    else:
        credential_id = ""
    return {
        "hour_bucket": hour_bucket,
        "call_count": call_count,
        "q_present": bool(q_present_raw),
        "result_count": result_count,
        "credential_id": credential_id,
    }


def _flush_aggregated_list_audit(
    *,
    principal: AppPrincipal,
    endpoint: str,
    state: _ListAuditState,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="app",
            actor_id=principal.app_key,
            action=_DIRECTORY_AUDIT_ACTION,
            target_type=_DIRECTORY_AUDIT_TARGET_TYPE,
            target_id=principal.app_key,
            metadata={
                "endpoint": endpoint,
                "q_present": state["q_present"],
                "result_count": state["result_count"],
                "credential_id": state["credential_id"],
                "call_count": state["call_count"],
                "hour_bucket": state["hour_bucket"],
            },
        ),
    )


def _directory_response(
    payload: dict[str, JsonValue],
    *,
    directory_snapshot: dict[str, JsonValue] | None = None,
) -> JsonResponse:
    payload["directory_snapshot"] = directory_snapshot or build_directory_snapshot()
    response = json_response(payload, status=HTTPStatus.OK)
    response[_CACHE_CONTROL_HEADER] = _CACHE_CONTROL_VALUE
    return response


def _authentication_failed_response() -> JsonResponse:
    return json_response(
        build_error_response(ErrorCode.AUTHENTICATION_FAILED, _AUTHENTICATION_FAILED_MESSAGE),
        status=HTTPStatus.UNAUTHORIZED,
    )


def _permission_denied_response(message: str) -> JsonResponse:
    return json_response(
        build_error_response(ErrorCode.PERMISSION_DENIED, message),
        status=HTTPStatus.FORBIDDEN,
    )


def _not_found_response(message: str, *, reason: str) -> JsonResponse:
    return json_response(
        build_error_response(
            ErrorCode.NOT_FOUND,
            message,
            {"reason": reason},
        ),
        status=HTTPStatus.NOT_FOUND,
    )


def _snapshot_conflict_response(
    *,
    reason: str,
    expected_snapshot_id: str,
    actual_snapshot_id: str,
) -> JsonResponse:
    return json_response(
        build_error_response(
            ErrorCode.CONFLICT,
            _SNAPSHOT_CONFLICT_MESSAGE,
            {
                "reason": reason,
                "expected_snapshot_id": expected_snapshot_id,
                "actual_snapshot_id": actual_snapshot_id,
            },
        ),
        status=HTTPStatus.CONFLICT,
    )


def _too_many_requests_response(retry_after_seconds: int) -> JsonResponse:
    response = json_response(
        build_error_response(ErrorCode.THROTTLED, _TOO_MANY_REQUESTS_MESSAGE),
        status=HTTPStatus.TOO_MANY_REQUESTS,
    )
    response[_RETRY_AFTER_HEADER] = str(retry_after_seconds)
    return response
