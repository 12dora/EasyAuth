from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from django.db import connection
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from easyauth.accounts.directory_references import (
    AmbiguousDirectoryReferenceError,
    InvalidDirectoryReferenceError,
    resolve_department_scope,
    resolve_directory_user,
    resolve_user_mirror,
)
from easyauth.accounts.directory_snapshot import build_directory_snapshot
from easyauth.accounts.models import DingTalkUserMirror, UserMirror
from easyauth.api.directory_auth import authenticate_capability_and_throttle
from easyauth.api.directory_payloads import (
    DINGTALK_STATUS_ACTIVE,
    build_manager_full_item,
    build_user_detail,
    build_user_list_items,
    removed_directory_user_item,
)
from easyauth.api.directory_responses import (
    directory_response,
    not_found_response,
    record_directory_audit,
    reference_error_response,
    snapshot_conflict_response,
)
from easyauth.api.pagination import Pagination, pagination_item, total_pages
from easyauth.applications.services import AppPrincipal

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from easyauth.api.errors import JsonValue

_USER_NOT_FOUND_MESSAGE: Final = "用户不存在。"
_NO_MANAGER_MESSAGE: Final = "用户没有直接主管。"
_DEFAULT_PAGE: Final = 1
_DEFAULT_PAGE_SIZE: Final = 20
_MAX_PAGE: Final = 100_000
_MAX_USERS_PAGE_SIZE: Final = 200


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
    match authenticate_capability_and_throttle(request, app_key):
        case AppPrincipal() as principal:
            pass
        case JsonResponse() as response:
            return response

    snapshot_before = build_directory_snapshot()
    requested_snapshot_id = request.GET.get("snapshot_id", "").strip()
    current_snapshot_id = cast("str", snapshot_before["snapshot_id"])
    if requested_snapshot_id and requested_snapshot_id != current_snapshot_id:
        return snapshot_conflict_response(
            reason="snapshot_mismatch",
            expected_snapshot_id=requested_snapshot_id,
            actual_snapshot_id=current_snapshot_id,
        )

    page = _page_request(request, max_page_size=_MAX_USERS_PAGE_SIZE)
    try:
        queryset = _filtered_users(request)
    except (AmbiguousDirectoryReferenceError, InvalidDirectoryReferenceError) as error:
        return reference_error_response(error)
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
        return snapshot_conflict_response(
            reason="snapshot_changed",
            expected_snapshot_id=current_snapshot_id,
            actual_snapshot_id=final_snapshot_id,
        )
    record_directory_audit(
        principal=principal,
        endpoint="users",
        result_count=len(rows),
        q_present=bool(request.GET.get("q", "").strip()),
        aggregated=True,
    )
    return directory_response(payload, directory_snapshot=snapshot_after)


@require_http_methods(["GET"])
def directory_user_detail(request: HttpRequest, app_key: str, user_ref: str) -> JsonResponse:
    match authenticate_capability_and_throttle(request, app_key):
        case AppPrincipal() as principal:
            pass
        case JsonResponse() as response:
            return response

    try:
        detail = _resolve_user_detail(user_ref)
    except (AmbiguousDirectoryReferenceError, InvalidDirectoryReferenceError) as error:
        return reference_error_response(error)
    if detail is None:
        return not_found_response(_USER_NOT_FOUND_MESSAGE, reason="user_not_found")
    record_directory_audit(
        principal=principal,
        endpoint="user_detail",
        result_count=1,
        q_present=False,
        aggregated=False,
    )
    return directory_response(detail)


@require_http_methods(["GET"])
def directory_user_manager(request: HttpRequest, app_key: str, user_ref: str) -> JsonResponse:
    match authenticate_capability_and_throttle(request, app_key):
        case AppPrincipal() as principal:
            pass
        case JsonResponse() as response:
            return response

    try:
        subject = _resolve_subject(user_ref)
    except (AmbiguousDirectoryReferenceError, InvalidDirectoryReferenceError) as error:
        return reference_error_response(error)
    if subject is None:
        return not_found_response(_USER_NOT_FOUND_MESSAGE, reason="user_not_found")
    manager = _resolve_manager(subject)
    if manager is None:
        return not_found_response(_NO_MANAGER_MESSAGE, reason="no_manager")
    payload = build_manager_full_item(manager)
    record_directory_audit(
        principal=principal,
        endpoint="user_manager",
        result_count=1,
        q_present=False,
        aggregated=False,
    )
    return directory_response(payload)


@require_http_methods(["GET"])
def directory_user_subordinates(
    request: HttpRequest,
    app_key: str,
    user_ref: str,
) -> JsonResponse:
    match authenticate_capability_and_throttle(request, app_key):
        case AppPrincipal() as principal:
            pass
        case JsonResponse() as response:
            return response

    try:
        subject = _resolve_subject(user_ref)
    except (AmbiguousDirectoryReferenceError, InvalidDirectoryReferenceError) as error:
        return reference_error_response(error)
    if subject is None:
        return not_found_response(_USER_NOT_FOUND_MESSAGE, reason="user_not_found")
    manager_dingtalk_id = _subject_dingtalk_user_id(subject)
    if not manager_dingtalk_id or subject.dingtalk_user is None:
        items: list[JsonValue] = []
    else:
        rows = list(
            DingTalkUserMirror.objects.filter(
                source_slug=subject.dingtalk_user.source_slug,
                corp_id=subject.dingtalk_user.corp_id,
                manager_userid=manager_dingtalk_id,
                status=DINGTALK_STATUS_ACTIVE,
            ).order_by("name", "source_slug", "corp_id", "user_id"),
        )
        items = build_user_list_items(rows)
    payload: dict[str, JsonValue] = {"data": items}
    record_directory_audit(
        principal=principal,
        endpoint="user_subordinates",
        result_count=len(items),
        q_present=False,
        aggregated=False,
    )
    return directory_response(payload)


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
        department_scope = resolve_department_scope(department_id)
        if department_scope is None:
            return DingTalkUserMirror.objects.none()
        source_slug, corp_id, resolved_department_id = department_scope
        queryset = _filter_by_department(
            queryset.filter(source_slug=source_slug, corp_id=corp_id),
            resolved_department_id,
        )
    manager_id = request.GET.get("manager_id", "").strip()
    if manager_id:
        manager = resolve_directory_user(manager_id)
        if manager is None:
            return DingTalkUserMirror.objects.none()
        queryset = queryset.filter(
            source_slug=manager.source_slug,
            corp_id=manager.corp_id,
            manager_userid=manager.user_id,
        )
    return queryset.order_by("name", "source_slug", "corp_id", "user_id")


def _filter_by_department(
    queryset: QuerySet[DingTalkUserMirror],
    department_id: str,
) -> QuerySet[DingTalkUserMirror]:
    # 直接成员(不递归)。PostgreSQL 用 JSON 数组 contains; SQLite 测试库无此 lookup,
    # 退化为带引号子串匹配(镜像里 department_ids 存字符串数组, 语义一致)。
    if connection.features.supports_json_field_contains:
        return queryset.filter(department_ids__contains=[department_id])
    return queryset.filter(department_ids__icontains=f'"{department_id}"')


def _resolve_user_detail(user_ref: str) -> dict[str, JsonValue] | None:
    dingtalk_user = resolve_directory_user(user_ref)
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
    dingtalk_user = resolve_directory_user(user_ref)
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
                source_slug=subject.dingtalk_user.source_slug,
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
    rows = list(
        DingTalkUserMirror.objects.filter(
            source_slug=subject.user_mirror.dingtalk_source_slug,
            corp_id=subject.user_mirror.dingtalk_corp_id,
            user_id=manager_userid,
        ).order_by("source_slug", "corp_id", "user_id")[:2],
    )
    return rows[0] if len(rows) == 1 else None


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
