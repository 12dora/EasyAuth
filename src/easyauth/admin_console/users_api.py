from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final

from django.db.models import Q
from django.http import HttpRequest, JsonResponse

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.admin_console.api_payloads import list_payload, paginated_list_payload
from easyauth.admin_console.api_responses import error_response, json_response
from easyauth.admin_console.operation_filters import paginate_queryset
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode
from easyauth.api.pagination import pagination_item
from easyauth.lifecycle.models import TASK_OPEN_STATUSES, HandoverTask

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from easyauth.api.errors import JsonValue

USER_SEARCH_DEFAULT_LIMIT: Final = 10
USER_SEARCH_MAX_LIMIT: Final = 50


def console_user_search(request: HttpRequest) -> JsonResponse:
    # 两种形态共用一个端点:
    # 1) 选人控件检索(默认): 按姓名/邮箱/Authentik 用户 ID/工号模糊检索活跃用户, limit 截断;
    # 2) 人员列表(带 page 参数): 全状态分页, 支持 status 筛选与"部门已变更"提示(M4)。
    if request.method != "GET":
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求方法无效。",
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )
    match require_console_actor(request):
        case JsonResponse() as response:
            return response
        case _:
            pass

    if request.GET.get("page"):
        return _people_page(request)
    query = request.GET.get("q", "").strip()
    users = UserMirror.objects.filter(status=USER_STATUS_ACTIVE)
    if query:
        users = _apply_query_filter(users, query)
    items: list[JsonValue] = [
        _user_item(user) for user in users.order_by("name", "authentik_user_id")[: _limit(request)]
    ]
    return json_response(list_payload(items))


def _people_page(request: HttpRequest) -> JsonResponse:
    users = UserMirror.objects.all()
    status = request.GET.get("status", "").strip()
    if status:
        users = users.filter(status=status)
    query = request.GET.get("q", "").strip()
    if query:
        users = _apply_query_filter(users, query)
    page = paginate_queryset(users.order_by("name", "authentik_user_id"), request.GET)
    items: list[JsonValue] = [_person_item(user) for user in page.items]
    return json_response(
        paginated_list_payload(items=items, pagination=pagination_item(page)),
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
        "email": user.email,
        "department": user.department,
    }


def _person_item(user: UserMirror) -> dict[str, JsonValue]:
    item = _user_item(user)
    item["status"] = user.status
    item["department_changed_at"] = datetime_value(user.department_changed_at)
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
