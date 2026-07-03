from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final

from django.db.models import Q
from django.http import HttpRequest, JsonResponse

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.admin_console.api_payloads import list_payload
from easyauth.admin_console.api_responses import error_response, json_response
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

USER_SEARCH_DEFAULT_LIMIT: Final = 10
USER_SEARCH_MAX_LIMIT: Final = 50


def console_user_search(request: HttpRequest) -> JsonResponse:
    # 按姓名/邮箱/Authentik 用户 ID/工号模糊检索活跃用户镜像, 供控制台选人控件使用。
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

    query = request.GET.get("q", "").strip()
    users = UserMirror.objects.filter(status=USER_STATUS_ACTIVE)
    if query:
        users = users.filter(
            Q(name__icontains=query)
            | Q(email__icontains=query)
            | Q(authentik_user_id__icontains=query)
            | Q(employee_number__icontains=query),
        )
    items: list[JsonValue] = [
        _user_item(user) for user in users.order_by("name", "authentik_user_id")[: _limit(request)]
    ]
    return json_response(list_payload(items))


def _user_item(user: UserMirror) -> dict[str, JsonValue]:
    return {
        "user_id": user.authentik_user_id,
        "name": user.name,
        "email": user.email,
        "department": user.department,
    }


def _limit(request: HttpRequest) -> int:
    raw_limit = request.GET.get("limit", "")
    try:
        limit = int(raw_limit) if raw_limit else USER_SEARCH_DEFAULT_LIMIT
    except ValueError:
        return USER_SEARCH_DEFAULT_LIMIT
    return max(1, min(limit, USER_SEARCH_MAX_LIMIT))
