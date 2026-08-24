"""处理生命周期交接任务的列表, 创建, 详情与修改接口。"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from django.http import HttpRequest, JsonResponse
from pydantic import ValidationError

from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.admin_console.api_payloads import paginated_list_payload
from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.lifecycle_api_serializers import (
    HandoverTaskCreatePayload,
    HandoverTaskPatchPayload,
    not_found,
    task_or_none,
    validation_error,
)
from easyauth.admin_console.operation_filters import (
    OperationFilterValidationError,
    operation_filter_error_response,
    paginate_queryset,
)
from easyauth.api.errors import ErrorCode
from easyauth.api.pagination import pagination_item
from easyauth.lifecycle.api_payloads import SURFACE_CONSOLE, console_task_list_item
from easyauth.lifecycle.api_payloads import task_detail as v2_task_detail
from easyauth.lifecycle.errors import HandoverConflictError
from easyauth.lifecycle.handover_actions import cancel_task, delete_task
from easyauth.lifecycle.models import (
    ACTION_STATUS_BLOCKED,
    ASSIGNEE_STATE_VALUES,
    HANDOVER_KIND_VALUES,
    TASK_STATUS_VALUES,
    HandoverTask,
)
from easyauth.lifecycle.offboarding import (
    HandoverCreationSpec,
    ensure_handover_task,
    start_offboarding,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from easyauth.api.errors import JsonValue
    from easyauth.api.pagination import Pagination


def lifecycle_handover_tasks(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method == "GET":
        queryset = HandoverTask.objects.select_related("subject_user").order_by(
            "-created_at",
            "-id",
        )
        filtered_queryset = _filter_handover_tasks(queryset, request)
        if isinstance(filtered_queryset, JsonResponse):
            return filtered_queryset
        queryset = filtered_queryset
        try:
            page = paginate_queryset(queryset, request.GET)
        except OperationFilterValidationError as exc:
            return operation_filter_error_response(exc)
        items: list[JsonValue] = [console_task_list_item(task) for task in page.items]
        return json_response(
            paginated_list_payload(
                items=items,
                pagination=pagination_item(cast("Pagination", cast("object", page))),
            ),
        )
    if request.method == "POST":
        return _create_task(request, actor_id)
    return method_not_allowed_response()


def _filter_handover_tasks(
    queryset: QuerySet[HandoverTask],
    request: HttpRequest,
) -> QuerySet[HandoverTask] | JsonResponse:
    status = request.GET.get("status", "").strip()
    if status in TASK_STATUS_VALUES:
        queryset = queryset.filter(status=status)
    elif status:
        return operation_filter_error_response(
            OperationFilterValidationError(
                key="status",
                value=status,
                message="status 必须为 pending、in_progress、completed 或 cancelled。",
            ),
        )
    kind = request.GET.get("kind", "").strip()
    if kind in HANDOVER_KIND_VALUES:
        queryset = queryset.filter(kind=kind)
    elif kind:
        return operation_filter_error_response(
            OperationFilterValidationError(
                key="kind",
                value=kind,
                message="kind 必须为 offboard、transfer、pre_offboard 或 reassign。",
            ),
        )
    assignee_state = request.GET.get("assignee_state", "").strip()
    if assignee_state:
        if assignee_state not in ASSIGNEE_STATE_VALUES:
            return error_response(
                ErrorCode.SEMANTIC_VALIDATION_ERROR,
                "assignee_state 枚举非法。",
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        queryset = queryset.filter(assignee_state=assignee_state)
    blocked = request.GET.get("blocked", "").strip().lower()
    if blocked in {"true", "1"}:
        queryset = queryset.filter(app_actions__status=ACTION_STATUS_BLOCKED).distinct()
    elif blocked in {"false", "0"}:
        queryset = queryset.exclude(app_actions__status=ACTION_STATUS_BLOCKED).distinct()
    elif blocked:
        return error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            "blocked 必须为 true 或 false。",
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    return queryset


def lifecycle_handover_task_detail(
    request: HttpRequest,
    task_id: int,
) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    task = task_or_none(task_id)
    if task is None:
        return not_found("交接单不存在。")
    return _handle_task_detail_method(request, task, actor_id)


def _handle_task_detail_method(
    request: HttpRequest,
    task: HandoverTask,
    actor_id: str,
) -> JsonResponse:
    if request.method == "GET":
        return json_response({"handover_task": v2_task_detail(task, surface=SURFACE_CONSOLE)})
    if request.method == "PATCH":
        return _patch_task(request, task, actor_id)
    if request.method == "DELETE":
        try:
            delete_task(task, actor_id=actor_id)
        except HandoverConflictError as error:
            return error_response(
                ErrorCode.SEMANTIC_VALIDATION_ERROR,
                str(error),
                status=HTTPStatus.CONFLICT,
            )
        return json_response({"deleted": True})
    return method_not_allowed_response()


def _create_task(request: HttpRequest, actor_id: str) -> JsonResponse:
    try:
        payload = HandoverTaskCreatePayload.model_validate_json(request.body)
    except ValidationError as exc:
        return validation_error("建单参数无效。", {"errors": str(exc)})
    if payload.kind not in HANDOVER_KIND_VALUES:
        return validation_error("交接类型必须为 offboard 或 transfer。")
    subject = UserMirror.objects.filter(authentik_user_id=payload.user_id).first()
    if subject is None:
        return validation_error("人员不存在。")
    if subject.authentik_user_id.startswith(LOCAL_ADMIN_SUBJECT_PREFIX):
        return validation_error("系统内置管理员不参与离职/转岗交接。")
    if payload.kind == "offboard":
        # 手动离职建单: 在职员工提前交接时不禁号; 已离职人员补单则补齐立即项。
        if subject.status == USER_STATUS_ACTIVE:
            task, created = ensure_handover_task(
                subject=subject,
                kind=payload.kind,
                created_by=actor_id,
                spec=HandoverCreationSpec(reason=payload.reason),
            )
        else:
            result = start_offboarding(subject, created_by=actor_id)
            task, created = result.task, result.created
    else:
        task, created = ensure_handover_task(
            subject=subject,
            kind=payload.kind,
            created_by=actor_id,
            spec=HandoverCreationSpec(reason=payload.reason),
        )
    status = HTTPStatus.CREATED if created else HTTPStatus.OK
    return json_response(
        {"handover_task": v2_task_detail(task, surface=SURFACE_CONSOLE)},
        status=status,
    )


def _patch_task(request: HttpRequest, task: HandoverTask, actor_id: str) -> JsonResponse:
    try:
        payload = HandoverTaskPatchPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return validation_error("交接单参数无效。", {"errors": str(exc)})
    if payload.cancel:
        try:
            task = cancel_task(task, actor_id=actor_id)
        except HandoverConflictError as error:
            return error_response(
                ErrorCode.SEMANTIC_VALIDATION_ERROR,
                str(error),
                status=HTTPStatus.CONFLICT,
            )
        return json_response(
            {"handover_task": v2_task_detail(task, surface=SURFACE_CONSOLE)},
        )
    # app_actions 已删除: 无 cancel 的 PATCH 无操作, 返回最新详情。
    return json_response(
        {"handover_task": v2_task_detail(task, surface=SURFACE_CONSOLE)},
    )
