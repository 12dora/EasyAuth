from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from django.http import HttpRequest, JsonResponse

from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.operation_filters import paginate_queryset
from easyauth.api.errors import ErrorCode
from easyauth.api.pagination import pagination_item
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.webhooks.delivery import redeliver
from easyauth.workflows.models import (
    APPROVAL_STATUS_VALUES,
    ApprovalInstance,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from easyauth.api.errors import JsonValue

type JsonObject = dict[str, "JsonValue"]


def operations_approval_instances(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str():
            pass
        case JsonResponse() as response:
            return response
    if request.method != "GET":
        return method_not_allowed_response()
    page = paginate_queryset(_filtered_instances(request), request.GET)
    items: list[JsonValue] = [_instance_item(instance) for instance in page.items]
    return json_response({"data": items, "pagination": pagination_item(page)})


def operations_approval_instance_redeliver(
    request: HttpRequest,
    instance_id: str,
) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    instance = (
        ApprovalInstance.objects.select_related("app", "template", "completion_delivery")
        .filter(id=instance_id)
        .first()
    )
    if instance is None:
        return error_response(
            ErrorCode.NOT_FOUND,
            "审批实例不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    if instance.completion_delivery is None:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "该实例没有可重投的结果投递。",
            status=HTTPStatus.BAD_REQUEST,
        )
    _ = redeliver(instance.completion_delivery)
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor_id,
            action="approval_delivery_redelivered",
            target_type="approval_instance",
            target_id=str(instance.id),
            metadata={
                "app_key": instance.app.app_key,
                "delivery_id": instance.completion_delivery.delivery_id,
            },
        ),
    )
    return json_response({"approval_instance": _instance_item(instance)})


def _filtered_instances(request: HttpRequest) -> QuerySet[ApprovalInstance]:
    queryset = ApprovalInstance.objects.select_related(
        "app",
        "template",
        "originator_user",
        "completion_delivery",
    ).order_by("-created_at")
    status = request.GET.get("status", "").strip()
    if status and status in APPROVAL_STATUS_VALUES:
        queryset = queryset.filter(status=status)
    app_key = request.GET.get("app_key", "").strip()
    if app_key:
        queryset = queryset.filter(app__app_key=app_key)
    return queryset


def _instance_item(instance: ApprovalInstance) -> JsonObject:
    delivery = instance.completion_delivery
    return {
        "instance_id": str(instance.id),
        "app_key": instance.app.app_key,
        "template_key": instance.template.key,
        "biz_key": instance.biz_key,
        "status": instance.status,
        "originator_user_id": instance.originator_user.authentik_user_id,
        "dingtalk_process_instance_id": instance.dingtalk_process_instance_id,
        "delivery_state": instance.delivery_state(),
        "delivery_attempts": delivery.attempts if delivery is not None else 0,
        "delivery_last_error": delivery.last_error if delivery is not None else "",
        "last_error": instance.last_error,
        "created_at": instance.created_at.isoformat(),
        "completed_at": (
            instance.completed_at.isoformat() if instance.completed_at is not None else None
        ),
    }
