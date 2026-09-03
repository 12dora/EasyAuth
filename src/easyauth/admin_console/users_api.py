from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final, cast

from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

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
from easyauth.api.ordering import parse_ordering
from easyauth.api.pagination import pagination_item
from easyauth.audit.services import AuditRecord, AuditService
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
PEOPLE_LIST_ORDERING: Final[dict[str, str]] = {
    "name": "name",
    "department": "department",
    "email": "email",
    "status": "status",
}
PEOPLE_LIST_DEFAULT_ORDER: Final[tuple[str, ...]] = ("name", "authentik_user_id")
SELF_REVOKE_ADMIN_MESSAGE: Final = "不能取消自己的管理员权限。"
CONSOLE_ADMIN_UPDATED_ACTION: Final = "user_console_admin_updated"


class _ConsoleAdminPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    # StrictBool: pydantic 默认会把 "yes" / "0" / 1 强转成布尔。管理员标志是权限位,
    # 客户端发错类型必须 422 报错, 不能被静默强转成某个方向。
    is_console_admin: StrictBool


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


def console_user_console_admin(request: HttpRequest, user_id: str) -> JsonResponse:
    if request.method != "PUT":
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求方法无效。",
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    return _set_console_admin(request, actor_id=actor_id, user_id=user_id)


def _people_page(request: HttpRequest) -> JsonResponse:
    # 人员列表是员工目录: 内置本地管理员不展示(也就没有员工语义的离职/转岗入口)。
    match parse_ordering(request, PEOPLE_LIST_ORDERING, PEOPLE_LIST_DEFAULT_ORDER):
        case JsonResponse() as response:
            return response
        case tuple() as ordering:
            pass
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
        page = paginate_queryset(users.order_by(*ordering), request.GET)
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
    item["is_console_admin"] = user.is_console_admin
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


def _set_console_admin(
    request: HttpRequest,
    *,
    actor_id: str,
    user_id: str,
) -> JsonResponse:
    user = _directory_person(user_id)
    if user is None:
        return error_response(
            ErrorCode.NOT_FOUND,
            "用户不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    try:
        payload = _ConsoleAdminPayload.model_validate_json(request.body or b"{}")
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    if (
        not payload.is_console_admin
        and user.is_console_admin
        and user.authentik_user_id == actor_id
    ):
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            SELF_REVOKE_ADMIN_MESSAGE,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    if user.is_console_admin == payload.is_console_admin:
        return json_response({"user": _person_item(user)})
    user.is_console_admin = payload.is_console_admin
    with transaction.atomic():
        user.save(update_fields=["is_console_admin", "updated_at"])
        _record_console_admin_change(actor_id=actor_id, user=user)
    return json_response({"user": _person_item(user)})


def _directory_person(user_id: str) -> UserMirror | None:
    # 人员管理目录不含 break-glass 本地管理员; 系统账号不可在此改管理员标志。
    if user_id.startswith(LOCAL_ADMIN_SUBJECT_PREFIX):
        return None
    return UserMirror.objects.filter(authentik_user_id=user_id).first()


def _record_console_admin_change(*, actor_id: str, user: UserMirror) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=actor_id,
            action=CONSOLE_ADMIN_UPDATED_ACTION,
            target_type="user",
            target_id=user.authentik_user_id,
            metadata={"is_console_admin": user.is_console_admin},
        ),
    )


def _limit(request: HttpRequest) -> int:
    raw_limit = request.GET.get("limit", "")
    try:
        limit = int(raw_limit) if raw_limit else USER_SEARCH_DEFAULT_LIMIT
    except ValueError:
        return USER_SEARCH_DEFAULT_LIMIT
    return max(1, min(limit, USER_SEARCH_MAX_LIMIT))
