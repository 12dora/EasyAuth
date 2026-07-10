from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, cast

from django.db.models import Q
from django.http import HttpRequest, JsonResponse

from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.admin_console.api_payloads import list_payload, paginated_list_payload
from easyauth.admin_console.api_responses import error_response, json_response
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.operation_filters import (
    OperationFilterValidationError,
    operation_filter_error_response,
    paginate_queryset,
)
from easyauth.api.errors import ErrorCode
from easyauth.api.pagination import pagination_item
from easyauth.lifecycle.models import TASK_OPEN_STATUSES, HandoverTask

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from easyauth.api.errors import JsonValue
    from easyauth.api.pagination import Pagination

USER_SEARCH_DEFAULT_LIMIT: Final = 10
USER_SEARCH_MAX_LIMIT: Final = 50
USER_SEARCH_PURPOSE_EMPLOYEE: Final = "employee"
USER_SEARCH_PURPOSE_APPROVER: Final = "approver"
USER_SEARCH_PURPOSES: Final = frozenset(
    {USER_SEARCH_PURPOSE_EMPLOYEE, USER_SEARCH_PURPOSE_APPROVER},
)


def console_users(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求方法无效。",
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )
    match require_superuser(request):
        case JsonResponse() as response:
            return response
        case _:
            pass
    return _people_page(request)


def console_user_options(request: HttpRequest) -> JsonResponse:
    if request.method != "GET":
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求方法无效。",
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )
    match require_superuser(request):
        case JsonResponse() as response:
            return response
        case _:
            pass

    query = request.GET.get("q", "").strip()
    if query == "":
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "q 不得为空。",
            {"field": "q"},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    purpose = request.GET.get("purpose", USER_SEARCH_PURPOSE_EMPLOYEE).strip()
    if purpose not in USER_SEARCH_PURPOSES:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "purpose 仅支持 employee 或 approver。",
            {"field": "purpose"},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    users = UserMirror.objects.filter(status=USER_STATUS_ACTIVE)
    if purpose == USER_SEARCH_PURPOSE_EMPLOYEE:
        # 本地管理员是 break-glass 系统账号。它不进入员工选择控件。交接接收人与成员都在此列。
        users = users.exclude(authentik_user_id__startswith=LOCAL_ADMIN_SUBJECT_PREFIX)
    users = _apply_query_filter(users, query)
    items: list[JsonValue] = [
        _user_item(user) for user in users.order_by("name", "authentik_user_id")[: _limit(request)]
    ]
    return json_response(list_payload(items))


def _people_page(request: HttpRequest) -> JsonResponse:
    # 人员列表是员工目录: 内置本地管理员不展示(也就没有员工语义的离职/转岗入口)。
    users = UserMirror.objects.exclude(
        authentik_user_id__startswith=LOCAL_ADMIN_SUBJECT_PREFIX,
    )
    status = request.GET.get("status", "").strip()
    if status:
        users = users.filter(status=status)
    query = request.GET.get("q", "").strip()
    if query:
        users = _apply_query_filter(users, query)
    try:
        page = paginate_queryset(users.order_by("name", "authentik_user_id"), request.GET)
    except OperationFilterValidationError as exc:
        return operation_filter_error_response(exc)
    items: list[JsonValue] = [_person_item(user) for user in page.items]
    return json_response(
        paginated_list_payload(
            items=items,
            pagination=pagination_item(cast("Pagination", cast("object", page))),
        ),
    )


def _apply_query_filter(
    users: QuerySet[UserMirror],
    query: str,
) -> QuerySet[UserMirror]:
    return users.filter(
        Q(name__icontains=query)
        | Q(email__icontains=query)
        | Q(authentik_user_id__icontains=query)
        | Q(employee_number__icontains=query),
    )


def _user_item(user: UserMirror) -> dict[str, JsonValue]:
    return {
        "user_id": user.authentik_user_id,
        "name": user.name,
    }


def _person_item(user: UserMirror) -> dict[str, JsonValue]:
    item: dict[str, JsonValue] = {
        **_user_item(user),
        "email": user.email,
        "department": user.department,
    }
    item["status"] = user.status
    open_task = (
        HandoverTask.objects.filter(
            subject_user=user,
            status__in=TASK_OPEN_STATUSES,
        )
        .only("id", "kind")
        .first()
    )
    item["open_handover_task_id"] = open_task.id if open_task is not None else None
    item["open_handover_kind"] = open_task.kind if open_task is not None else ""
    return item


def _limit(request: HttpRequest) -> int:
    raw_limit = request.GET.get("limit", "")
    try:
        limit = int(raw_limit) if raw_limit else USER_SEARCH_DEFAULT_LIMIT
    except ValueError:
        return USER_SEARCH_DEFAULT_LIMIT
    return max(1, min(limit, USER_SEARCH_MAX_LIMIT))
